"""The agent loop: call model, route tool, repeat — under three hard caps.

Plan NFR-3 (5 min wall clock, 20 tool calls), NFR-8 (30s per tool call), and
FR-15 (a write tool is refused unless can_write is set on this agent).
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions.errors import AppException
from app.models import Agent, Run, as_utc, utcnow
from app.runtime import router
from app.runtime.logger import RunLogger
from app.runtime.models_api import ModelProvider, get_provider


@dataclass
class ExecutionResult:
    status: str  # succeeded | failed
    output: str
    error: str | None = None
    tool_calls: int = 0
    # False when another attempt cannot succeed (the provider rejected the request).
    retryable: bool = True


class RunTimeout(Exception):
    pass


class ToolBudgetExceeded(Exception):
    pass


class EmptyTurn(Exception):
    """The provider answered with neither text nor a tool call. Seen from an
    overloaded endpoint as a 200 with an empty stream; worth another attempt."""


async def execute(
    session: AsyncSession,
    *,
    agent: Agent,
    logger: RunLogger,
    prompt_override: str | None = None,
    provider: ModelProvider | None = None,
) -> ExecutionResult:
    provider = provider or get_provider(agent.model)
    started = time.monotonic()
    deadline = started + settings.RUN_TIMEOUT_SECONDS

    tools, can_write = await router.build_tool_list(session, agent.id, agent.user_id)
    tool_schemas = [
        {"name": t.name, "description": t.description, "input_schema": t.schema}
        for t in tools
    ]

    await logger.info(
        f"model {agent.model} · {len(tool_schemas)} tools allowed "
        f"({sum(1 for t in tools if can_write.get(t.name)) } writable)"
    )

    variables = await prompt_variables(session, agent)
    system_prompt = render(agent.system_prompt, variables)
    user_prompt = render(prompt_override or agent.user_prompt or "Run.", variables)

    messages: list[dict[str, Any]] = [{"role": "user", "content": user_prompt}]
    calls_made = 0
    model_calls = 0

    try:
        while True:
            if time.monotonic() > deadline:
                raise RunTimeout(f"run exceeded {settings.RUN_TIMEOUT_SECONDS}s")

            model_calls += 1
            turn = await provider.complete(
                model=agent.model,
                system=system_prompt,
                messages=messages,
                tools=tool_schemas or None,
            )
            await logger.info(
                f"model call {model_calls} · {turn.input_tokens:,} in / "
                f"{turn.output_tokens:,} out"
            )

            if not turn.wants_tools and not turn.text.strip():
                raise EmptyTurn("the model returned nothing")

            if not turn.wants_tools:
                await logger.ok(
                    f"run succeeded in {time.monotonic() - started:.1f}s"
                )
                return ExecutionResult("succeeded", turn.text, tool_calls=calls_made)

            messages.append({"role": "assistant", "content": _assistant_blocks(turn)})

            results = []
            for tool_call in turn.tool_calls:
                calls_made += 1
                if calls_made > settings.MAX_TOOL_CALLS_PER_RUN:
                    raise ToolBudgetExceeded(
                        f"exceeded {settings.MAX_TOOL_CALLS_PER_RUN} tool calls"
                    )
                results.append(
                    await _run_one_tool(session, agent, logger, tool_call, can_write)
                )

            messages.append({"role": "user", "content": results})

    except (RunTimeout, ToolBudgetExceeded) as exc:
        await logger.error(f"run cancelled · {exc}")
        return ExecutionResult("failed", "", str(exc), calls_made, retryable=False)
    except EmptyTurn as exc:
        await logger.warn(f"empty answer · {exc}")
        return ExecutionResult("failed", "", str(exc), calls_made, retryable=True)
    except AppException as exc:
        await logger.error(f"run failed · {exc.message}")
        return ExecutionResult(
            "failed", "", exc.message, calls_made, retryable=getattr(exc, "retryable", True)
        )
    except Exception as exc:  # noqa: BLE001 - the run records why it died
        await logger.error(f"run failed · {type(exc).__name__}: {exc}")
        return ExecutionResult("failed", "", f"{type(exc).__name__}: {exc}", calls_made)


async def prompt_variables(session: AsyncSession, agent: Agent) -> dict[str, str]:
    """The placeholders the create screen advertises: {{last_run}}, {{now}}, {{agent_name}}."""
    previous = (
        await session.execute(
            select(Run)
            .where(Run.agent_id == agent.id, Run.status == "succeeded")
            .order_by(Run.ended_at.desc())
            .limit(1)
        )
    ).scalars().first()
    last = as_utc(previous.ended_at) if previous and previous.ended_at else None
    return {
        "last_run": last.isoformat(timespec="seconds") if last else "never",
        "now": utcnow().isoformat(timespec="seconds"),
        "agent_name": agent.name,
    }


def render(text: str, variables: dict[str, str]) -> str:
    """Replace {{name}} placeholders; unknown ones are left as written."""
    for key, value in variables.items():
        text = text.replace("{{" + key + "}}", value).replace("{{ " + key + " }}", value)
    return text


def _assistant_blocks(turn) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if turn.text:
        blocks.append({"type": "text", "text": turn.text})
    for call in turn.tool_calls:
        blocks.append(
            {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
        )
    return blocks


async def _run_one_tool(
    session: AsyncSession, agent: Agent, logger: RunLogger, tool_call, can_write: dict
) -> dict[str, Any]:
    """One tool call, always returning a tool_result — an error is a result, not a gap."""
    await logger.info(f"tool {tool_call.name} {_short(tool_call.arguments)}")
    try:
        value = await router.call(
            session,
            user_id=agent.user_id,
            tool_name=tool_call.name,
            arguments=tool_call.arguments,
            can_write=can_write,
        )
        await logger.info(f"← {_short(value)}")
        return {
            "type": "tool_result",
            "tool_use_id": tool_call.id,
            "content": _short(value, 4000),
        }
    except (router.ConnectionExpired, router.ConnectionMissing) as exc:
        await logger.error(f"← blocked · {exc}")
        return {
            "type": "tool_result",
            "tool_use_id": tool_call.id,
            "content": f"Blocked: {exc}",
            "is_error": True,
        }
    except router.ToolDenied as exc:
        await logger.warn(f"← refused · {exc}")
        return {
            "type": "tool_result",
            "tool_use_id": tool_call.id,
            "content": f"Refused: {exc}",
            "is_error": True,
        }
    except asyncio.TimeoutError:
        await logger.error(
            f"← {tool_call.name} cancelled after {settings.TOOL_CALL_TIMEOUT_SECONDS}s"
        )
        return {
            "type": "tool_result",
            "tool_use_id": tool_call.id,
            "content": "Tool call timed out",
            "is_error": True,
        }
    except Exception as exc:  # noqa: BLE001 - one bad tool must not kill the run
        await logger.error(f"← {type(exc).__name__}: {exc}")
        return {
            "type": "tool_result",
            "tool_use_id": tool_call.id,
            "content": f"{type(exc).__name__}: {exc}",
            "is_error": True,
        }


def _short(value: Any, limit: int = 200) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"
