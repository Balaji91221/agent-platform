"""The public A2A surface: one card and one JSON-RPC endpoint per agent.

Unauthenticated by cookie on purpose — the caller is another agent, not a
browser. Every route is guarded by the agent's own bearer token instead, and the
whole router is inert unless `A2A_ENABLED` is on.
"""

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.a2a import card as card_builder
from app.a2a import server, tokens
from app.config import settings
from app.db import get_session
from app.exceptions.errors import NotFoundException
from app.models import Agent, AgentTool

router = APIRouter(prefix="/a2a/agents", tags=["A2A"])


def _bearer(header: str | None) -> str | None:
    if not header or not header.lower().startswith("bearer "):
        return None
    return header[7:]


async def _agent(session: AsyncSession, agent_id: int) -> Agent:
    """404 whether A2A is off, the agent is gone, or the id never existed.

    The spec is explicit that a server must not reveal the existence of a
    resource the caller cannot reach, so all three answer the same way.
    """
    if not settings.A2A_ENABLED:
        raise NotFoundException("No such agent")
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise NotFoundException("No such agent")
    return agent


@router.get("/{agent_id}/.well-known/agent-card.json")
async def agent_card(agent_id: int, session: AsyncSession = Depends(get_session)):
    """Discovery. Public: a card names capabilities, never data or secrets."""
    agent = await _agent(session, agent_id)
    tools = (
        await session.execute(select(AgentTool).where(AgentTool.agent_id == agent.id))
    ).scalars().all()
    return card_builder.build(agent, list(tools))


@router.post("/{agent_id}")
async def rpc(
    agent_id: int,
    request: Request,
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
):
    """JSON-RPC 2.0. Errors ride in the 200 envelope, as the transport requires."""
    agent = await _agent(session, agent_id)

    if not tokens.verify(agent.id, _bearer(authorization)):
        # 401 for the HTTP layer, and the JSON-RPC envelope for the client that
        # only reads the body. The spec asks for one or the other; sending both
        # costs nothing and neither kind of client is left guessing.
        return JSONResponse(
            status_code=401,
            content=server.error(None, server.UNAUTHENTICATED, "A valid bearer token is required"),
        )

    try:
        body = await request.json()
    except ValueError:
        return server.error(None, server.PARSE_ERROR, "The body is not valid JSON")

    return await server.dispatch(session, agent, body)
