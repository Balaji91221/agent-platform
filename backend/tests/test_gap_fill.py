from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_a_provider_without_a_connector_is_rejected(session, user):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/connections", json={"kind": "api_key", "provider": "zendesk", "secret": "x"},
                         headers={"X-User-Id": str(user.id)})
        ok = await c.post("/connections", json={"kind": "api_key", "provider": "youtube", "secret": "x"},
                          headers={"X-User-Id": str(user.id)})
    assert r.status_code == 422 and "No connector for 'zendesk'" in r.text
    assert ok.status_code == 201


async def test_health_publishes_the_run_limits(session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/health")).json()
    assert body["limits"]["max_attempts"] == 3 and body["limits"]["run_timeout_seconds"] == 300
    assert body["limits"]["max_tool_calls_per_run"] == 20 and body["limits"]["retry_backoff_seconds"] == [1.0, 2.0, 4.0]
