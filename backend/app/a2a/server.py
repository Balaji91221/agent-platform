"""The A2A JSON-RPC method the platform implements: `SendMessage`.

Card + synchronous send, and nothing else. Every other method answers
`-32601 Method not found`, which is what a well-behaved client expects when a
capability the card already declares as `false` is asked for anyway.

The run happens in-process rather than through `enqueue_run`, because the caller
is blocking on the answer and a queued job would also be picked up by a worker —
running it twice. A2A v1.0 makes blocking the default for `SendMessage`, so
waiting here is the specified behaviour, not a shortcut.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, Run, as_utc, utcnow
from app.runtime.runs import claim_agent, perform_run

logger = logging.getLogger("app.a2a")

# JSON-RPC 2.0 reserved codes, plus the A2A-specific range from the spec.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
# A2A: -32001 TaskNotFound … -32009 VersionNotSupported.
UNSUPPORTED_OPERATION = -32004
# The spec reserves -32001..-32099 for A2A errors and gives no code for a failed
# credential — it names "HTTP 401, or a JSON-RPC custom error". -32000 is the one
# code in JSON-RPC's implementation-defined range that A2A has not claimed.
UNAUTHENTICATED = -32000


def error(request_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def result(request_id: Any, payload: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _text_of(message: dict) -> str:
    """Join every text part into the prompt the run is given.

    A part with no `text` is a file or data part — this build is text-only, and
    the card says so, so anything else is dropped rather than guessed at.
    """
    parts = message.get("parts")
    if not isinstance(parts, list):
        return ""
    texts = [p.get("text", "") for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str)]
    return "\n".join(t for t in texts if t).strip()


def _rfc3339(value) -> str:
    """A2A timestamps are protobuf `Timestamp`, which demands RFC 3339 UTC.

    SQLite hands back naive datetimes, and `.isoformat()` on one produces a
    string with no zone that a conformant client refuses to parse.
    """
    moment = as_utc(value) or utcnow()
    return moment.isoformat().replace("+00:00", "Z")


def _task(run: Run, context_id: str, text: str) -> dict:
    """A run, as an A2A Task. Terminal on return: the send was blocking."""
    state = "TASK_STATE_COMPLETED" if run.status == "succeeded" else "TASK_STATE_FAILED"
    task: dict[str, Any] = {
        "id": f"run-{run.id}",
        "contextId": context_id,
        "status": {
            "state": state,
            "timestamp": _rfc3339(run.ended_at),
        },
        "artifacts": [],
    }
    if run.status == "succeeded":
        task["artifacts"] = [
            {
                "artifactId": str(uuid.uuid4()),
                "name": "output",
                "parts": [{"text": run.output or ""}],
            }
        ]
    else:
        task["status"]["message"] = {
            "role": "ROLE_AGENT",
            "messageId": str(uuid.uuid4()),
            "parts": [{"text": run.error or "The run failed."}],
        }
    # Echo the caller's message so the task carries its own history.
    task["history"] = [
        {"role": "ROLE_USER", "messageId": str(uuid.uuid4()), "parts": [{"text": text}]}
    ]
    return task


async def send_message(session: AsyncSession, agent: Agent, params: dict, request_id: Any) -> dict:
    """Run the agent on the message text and answer with a terminal Task."""
    message = params.get("message")
    if not isinstance(message, dict):
        return error(request_id, INVALID_PARAMS, "params.message is required")

    text = _text_of(message)
    if not text:
        return error(request_id, INVALID_PARAMS, "params.message.parts must carry text")

    context_id = message.get("contextId") or str(uuid.uuid4())

    # One run at a time per agent — the same lock the scheduler and the UI use.
    if not await claim_agent(session, agent.id):
        return error(request_id, UNSUPPORTED_OPERATION, "This agent is already running.")

    run = Run(agent_id=agent.id, trigger="a2a", status="queued", attempt=0)
    session.add(run)
    await session.commit()
    await session.refresh(run)

    try:
        run = await perform_run(session, run.id, prompt_override=text)
    except Exception:
        logger.exception("a2a run failed for agent %s", agent.id)
        return error(request_id, INTERNAL_ERROR, "The run could not be completed.")

    return result(request_id, {"task": _task(run, context_id, text)})


async def dispatch(session: AsyncSession, agent: Agent, body: Any) -> dict:
    """Validate the JSON-RPC envelope, then route the one method we answer."""
    if not isinstance(body, dict):
        return error(None, INVALID_REQUEST, "The request body must be a JSON-RPC object")

    request_id = body.get("id")
    if body.get("jsonrpc") != "2.0":
        return error(request_id, INVALID_REQUEST, "jsonrpc must be '2.0'")

    method = body.get("method")
    params = body.get("params")
    if not isinstance(params, dict):
        params = {}

    if method == "SendMessage":
        return await send_message(session, agent, params, request_id)

    return error(request_id, METHOD_NOT_FOUND, f"This agent does not implement '{method}'")
