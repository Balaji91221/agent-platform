"""MCP servers: register (handshakes at once), list, retry, remove."""

from fastapi import APIRouter, Depends, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.dependencies.auth import get_current_user
from app.mcp.cache import qualified_names, refresh
from app.models import Agent, AgentTool, Credential, McpServer, User
from app.schemas.rest import McpServerCreate, McpServerOut
from app.security.crypto import encrypt
from app.security.ownership import get_owned_mcp_server, owned

router = APIRouter(prefix="/mcp-servers", tags=["MCP servers"])


@router.get("", response_model=list[McpServerOut])
async def list_servers(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    rows = (await session.execute(owned(McpServer, user.id))).scalars().all()
    return list(rows)


@router.post("", response_model=McpServerOut, status_code=status.HTTP_201_CREATED)
async def register(
    payload: McpServerCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Plan FR-10 — a broken server is reported with a reason, never hidden."""
    credential_id = None
    if payload.token:
        credential = Credential(ciphertext=encrypt(payload.token))
        session.add(credential)
        await session.commit()
        await session.refresh(credential)
        credential_id = credential.id

    server = McpServer(
        user_id=user.id,
        name=payload.name,
        url=payload.url,
        auth_kind=payload.auth_kind,
        credential_id=credential_id,
        status="handshake_failed",
    )
    session.add(server)
    await session.commit()
    await session.refresh(server)

    return await refresh(session, server)


@router.post("/{server_id}/handshake", response_model=McpServerOut)
async def rehandshake(
    server_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    server = await get_owned_mcp_server(session, server_id, user.id)
    return await refresh(session, server)


@router.get("/{server_id}/tools")
async def server_tools(
    server_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Tool names already carry the `mcp:{id}.` prefix, ready to grant to an agent."""
    server = await get_owned_mcp_server(session, server_id, user.id)
    return {
        "status": server.status,
        "tools": server.tools_json or [],
        "qualified_names": qualified_names(server),
    }


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove(
    server_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    server = await get_owned_mcp_server(session, server_id, user.id)
    # Grants that pointed at this server would otherwise dangle on agents
    # (shown in the UI, silently skipped at run time).
    await session.execute(
        delete(AgentTool).where(
            AgentTool.tool_name.like(f"mcp:{server.id}.%"),
            AgentTool.agent_id.in_(select(Agent.id).where(Agent.user_id == user.id)),
        )
    )
    if server.credential_id is not None:
        cred = await session.get(Credential, server.credential_id)
        if cred is not None:
            await session.delete(cred)
    await session.delete(server)
    await session.commit()
