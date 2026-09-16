"""Talks to Jenkins.

Three parameterised jobs live in `jenkins/casc.yaml` — `agent-create`,
`agent-deploy`, `agent-delete`. Each writes or removes one host entry.

Nothing here raises into a request handler. Jenkins being down is an ordinary
answer (`status="unavailable"`), not a reason a user cannot delete an agent.
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("app.cicd")

_SLUG_STRIP = re.compile(r"[^a-z0-9-]+")
_SLUG_EDGES = re.compile(r"^-+|-+$")


@dataclass(frozen=True)
class JobRun:
    """One build of one job, flattened for the API."""

    job: str
    # none | queued | running | success | failure | unavailable | disabled
    # "none" is never-run: distinct from "queued" so the UI knows not to poll.
    status: str
    build_number: int | None = None
    url: str | None = None
    message: str = ""


def agent_slug(agent_id: int, name: str) -> str:
    """A DNS label for an agent: lowercase, hyphenated, always unique by id.

    The id suffix is what makes it safe — two agents may share a name, but a
    host entry is a key, so it cannot collide.
    """
    base = _SLUG_EDGES.sub("", _SLUG_STRIP.sub("-", name.strip().lower()))
    base = base[:40] or "agent"
    return f"{base}-{agent_id}"


def host_entry(slug: str) -> str:
    """The line the jobs write, so the API can show it without asking Jenkins."""
    return f"{settings.AGENT_HOST_IP}\t{slug}.{settings.AGENT_HOST_DOMAIN}"


def _params(agent_id: int, name: str) -> dict[str, str]:
    return {
        "AGENT_ID": str(agent_id),
        "AGENT_SLUG": agent_slug(agent_id, name),
        "AGENT_NAME": name,
        "HOST_IP": settings.AGENT_HOST_IP,
        "HOST_DOMAIN": settings.AGENT_HOST_DOMAIN,
        "HOSTS_FILE": settings.AGENT_HOSTS_FILE,
    }


def _auth() -> tuple[str, str]:
    return (settings.JENKINS_USER, settings.JENKINS_PASSWORD)


def _base() -> str:
    return settings.JENKINS_URL.rstrip("/")


async def _crumb(client: httpx.AsyncClient) -> dict[str, str]:
    """Jenkins rejects a POST without a CSRF crumb.

    The crumb is bound to the session, so it must be fetched on the same client
    that sends the POST — hence the shared cookie jar rather than a cached value.
    """
    try:
        response = await client.get(f"{_base()}/crumbIssuer/api/json")
        if response.status_code != 200:
            return {}
        body = response.json()
        field = body.get("crumbRequestField")
        crumb = body.get("crumb")
        if isinstance(field, str) and isinstance(crumb, str):
            return {field: crumb}
    except (httpx.HTTPError, ValueError):
        # Crumbs are off on some installs; the POST then works without one.
        pass
    return {}


async def _queued_build(client: httpx.AsyncClient, queue_url: str) -> dict[str, Any] | None:
    """Wait for the queue item to turn into a build, then return that build.

    Jenkins answers a build request with a queue item, not a build — the number
    only exists once an executor picks it up.
    """
    for _ in range(20):
        response = await client.get(f"{queue_url.rstrip('/')}/api/json")
        if response.status_code != 200:
            return None
        item = response.json()
        executable = item.get("executable")
        if isinstance(executable, dict):
            return executable
        if item.get("cancelled"):
            return None
        await asyncio.sleep(0.5)
    return None


async def trigger(job: str, agent_id: int, name: str, *, wait: bool = False) -> JobRun:
    """Start one job. Never waits for the build to finish.

    `wait=False` returns the moment Jenkins accepts the request — measured at
    6.4s versus 0.3s for a create, because a queued build only gets its number
    once an executor picks it up. Agent create and delete use that: the user is
    not made to wait on CI, and the UI polls `jobs_for_agent` for the result.

    `wait=True` is for the Deploy button, where the build number is what the
    caller asked for and a short wait is the expected cost.
    """
    if not settings.JENKINS_ENABLED:
        return JobRun(job=job, status="disabled", message="JENKINS_ENABLED is false")

    try:
        async with httpx.AsyncClient(
            auth=_auth(), timeout=settings.JENKINS_TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            headers = await _crumb(client)
            response = await client.post(
                f"{_base()}/job/{job}/buildWithParameters",
                params=_params(agent_id, name),
                headers=headers,
            )
            if response.status_code not in (200, 201):
                logger.warning("jenkins %s refused the build: %s", job, response.status_code)
                return JobRun(
                    job=job,
                    status="failure",
                    message=f"Jenkins returned {response.status_code}",
                )

            queue_url = response.headers.get("Location")
            if not wait or not queue_url:
                return JobRun(job=job, status="queued", message="Queued")

            build = await _queued_build(client, queue_url)
            if build is None:
                return JobRun(job=job, status="queued", message="Waiting for an executor")

            number = build.get("number")
            return JobRun(
                job=job,
                status="running",
                build_number=number if isinstance(number, int) else None,
                url=build.get("url") if isinstance(build.get("url"), str) else None,
                message="Started",
            )
    except httpx.HTTPError as error:
        logger.warning("jenkins unreachable for %s: %s", job, error)
        return JobRun(job=job, status="unavailable", message="Jenkins is not reachable")


def _result_status(build: dict[str, Any]) -> str:
    if build.get("building"):
        return "running"
    result = build.get("result")
    return "success" if result == "SUCCESS" else "failure"


def _matches_agent(build: dict[str, Any], agent_id: int) -> bool:
    """A build belongs to an agent when its AGENT_ID parameter says so."""
    for action in build.get("actions") or []:
        if not isinstance(action, dict):
            continue
        for param in action.get("parameters") or []:
            if isinstance(param, dict) and param.get("name") == "AGENT_ID":
                return str(param.get("value")) == str(agent_id)
    return False


async def jobs_for_agent(agent_id: int) -> list[JobRun]:
    """The latest build of each of the three jobs for one agent.

    Reads the build parameters rather than storing build numbers, so there is no
    table to keep in step with Jenkins' own history.
    """
    names = [
        settings.JENKINS_CREATE_JOB,
        settings.JENKINS_DEPLOY_JOB,
        settings.JENKINS_DELETE_JOB,
    ]
    if not settings.JENKINS_ENABLED:
        return [JobRun(job=n, status="disabled", message="JENKINS_ENABLED is false") for n in names]

    tree = "builds[number,result,building,url,actions[parameters[name,value]]]"
    try:
        async with httpx.AsyncClient(
            auth=_auth(), timeout=settings.JENKINS_TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            out: list[JobRun] = []
            for name in names:
                response = await client.get(f"{_base()}/job/{name}/api/json", params={"tree": tree})
                if response.status_code != 200:
                    out.append(JobRun(job=name, status="unavailable", message="No such job"))
                    continue
                builds = response.json().get("builds") or []
                mine = next((b for b in builds if _matches_agent(b, agent_id)), None)
                if mine is None:
                    out.append(JobRun(job=name, status="none", message="Never run"))
                    continue
                number = mine.get("number")
                out.append(
                    JobRun(
                        job=name,
                        status=_result_status(mine),
                        build_number=number if isinstance(number, int) else None,
                        url=mine.get("url") if isinstance(mine.get("url"), str) else None,
                    )
                )
            return out
    except httpx.HTTPError as error:
        logger.warning("jenkins unreachable listing jobs: %s", error)
        return [
            JobRun(job=n, status="unavailable", message="Jenkins is not reachable") for n in names
        ]
