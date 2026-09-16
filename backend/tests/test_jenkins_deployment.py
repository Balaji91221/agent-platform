"""Jenkins wiring, with Jenkins absent — the state every developer starts in.

`JENKINS_ENABLED` is false in the test environment, so these prove the promise
that matters: agent CRUD never depends on a CI server being up.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.cicd import jenkins
from app.config import settings
from app.main import app


@pytest.fixture
async def client(session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _agent(client, name="Daily Digest") -> dict:
    r = await client.post("/agents", json={"name": name, "model": "claude-sonnet-5"})
    assert r.status_code == 201, r.text
    return r.json()


def test_slug_is_a_dns_label_keyed_by_id():
    assert jenkins.agent_slug(7, "Daily Digest!") == "daily-digest-7"
    # Two agents may share a name; a host entry is a key, so the id decides.
    assert jenkins.agent_slug(8, "Daily Digest!") == "daily-digest-8"


def test_slug_survives_a_name_with_nothing_usable_in_it():
    assert jenkins.agent_slug(3, "!!!") == "agent-3"
    assert jenkins.agent_slug(4, "--x--") == "x-4"


def test_host_entry_uses_the_configured_ip_and_domain():
    ip, fqdn = jenkins.host_entry("daily-digest-7").split("\t")
    assert ip == settings.AGENT_HOST_IP
    assert fqdn == f"daily-digest-7.{settings.AGENT_HOST_DOMAIN}"


async def test_create_and_delete_work_with_jenkins_off(client):
    """The whole point of JENKINS_ENABLED defaulting to false."""
    assert settings.JENKINS_ENABLED is False
    agent = await _agent(client)
    assert (await client.delete(f"/agents/{agent['id']}")).status_code == 204


async def test_deployment_reports_all_three_jobs_as_disabled(client):
    agent = await _agent(client)
    body = (await client.get(f"/agents/{agent['id']}/deployment")).json()

    assert body["slug"] == f"daily-digest-{agent['id']}"
    assert body["enabled"] is False
    assert [j["job"] for j in body["jobs"]] == ["agent-create", "agent-deploy", "agent-delete"]
    assert {j["status"] for j in body["jobs"]} == {"disabled"}


async def test_deploy_is_a_no_op_rather_than_an_error_when_jenkins_is_off(client):
    agent = await _agent(client)
    r = await client.post(f"/agents/{agent['id']}/deploy")

    assert r.status_code == 200
    assert r.json()["jobs"][0]["status"] == "disabled"


async def test_deployment_of_someone_elses_agent_is_a_404(client, session):
    """Ownership is checked on the CI routes too, not just on agent CRUD."""
    from app.models import Agent, User

    other = User(email="other@example.com")
    session.add(other)
    await session.commit()
    await session.refresh(other)
    agent = Agent(user_id=other.id, name="Theirs", model="claude-sonnet-5")
    session.add(agent)
    await session.commit()
    await session.refresh(agent)

    assert (await client.get(f"/agents/{agent.id}/deployment")).status_code == 404
    assert (await client.post(f"/agents/{agent.id}/deploy")).status_code == 404
