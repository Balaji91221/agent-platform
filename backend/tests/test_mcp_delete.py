"""Deleting an MCP server removes the grants that pointed at it."""

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.mcp.client import HandshakeResult
from app.mcp import client as mcp_client


async def test_deleting_a_server_removes_its_grants_from_agents(session, user, monkeypatch):
    async def ok(url, auth_kind="none", credential=None):
        return HandshakeResult(ok=True, tools=[{"name": "search"}], server_name="docs")
    monkeypatch.setattr(mcp_client, "handshake", ok)

    headers = {"X-User-Id": str(user.id)}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        server = (await c.post("/mcp-servers", json={"url": "http://mcp.test/mcp"}, headers=headers)).json()
        agent = (await c.post("/agents", json={
            "name": "A", "user_prompt": "x",
            "tools": [{"tool_name": f"mcp:{server['id']}.search"}, {"tool_name": "http.get"}],
        }, headers=headers)).json()
        assert [t["tool_name"] for t in agent["tools"]] == [f"mcp:{server['id']}.search", "http.get"]

        assert (await c.delete(f"/mcp-servers/{server['id']}", headers=headers)).status_code == 204
        after = (await c.get(f"/agents/{agent['id']}", headers=headers)).json()
    assert [t["tool_name"] for t in after["tools"]] == ["http.get"]


def test_http_post_advertises_its_body():
    from app.connectors.registry import get_tool

    schema = get_tool("http.post").schema
    assert set(schema["properties"]) == {"path", "body"}
