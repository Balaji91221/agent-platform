"""Builds an A2A Agent Card from an agent row.

The card is derived, never stored, so it is correct the moment an agent is
created, reflects a rename immediately, and is gone when the agent is deleted —
there is nothing to publish and nothing to keep in step.

Shapes follow the A2A v1.0 specification: `supportedInterfaces`, `skills`, and
`securitySchemes` keyed by scheme type.
"""

from __future__ import annotations

from app.config import settings
from app.models import Agent, AgentTool

# Relay agents answer in prose, and take prose.
TEXT_ONLY = ["text/plain"]


def endpoint_url(agent_id: int) -> str:
    return f"{settings.A2A_PUBLIC_URL.rstrip('/')}/a2a/agents/{agent_id}"


def card_url(agent_id: int) -> str:
    return f"{endpoint_url(agent_id)}/.well-known/agent-card.json"


def _skills(agent: Agent, tools: list[AgentTool]) -> list[dict]:
    """One skill for the agent itself, plus one per tool it may use.

    A caller choosing between agents reads skills, so the tools are worth
    naming: "can write to Gmail" is the kind of thing that decides the choice.
    """
    skills: list[dict] = [
        {
            "id": "run",
            "name": agent.name,
            "description": agent.description or f"Runs the {agent.name} agent.",
            "tags": ["agent", "relay"],
            "examples": [agent.user_prompt] if agent.user_prompt else [],
            "inputModes": TEXT_ONLY,
            "outputModes": TEXT_ONLY,
        }
    ]
    for tool in tools:
        access = "read and write" if tool.can_write else "read only"
        skills.append(
            {
                "id": f"tool:{tool.tool_name}",
                "name": tool.tool_name,
                "description": f"Uses {tool.tool_name} ({access}) while running.",
                "tags": ["tool", tool.tool_name.split(".")[0]],
                "examples": [],
                "inputModes": TEXT_ONLY,
                "outputModes": TEXT_ONLY,
            }
        )
    return skills


def build(agent: Agent, tools: list[AgentTool]) -> dict:
    return {
        "name": agent.name,
        "description": agent.description or f"A Relay agent running {agent.model}.",
        "supportedInterfaces": [
            {
                "url": endpoint_url(agent.id),
                "protocolBinding": "JSONRPC",
                "protocolVersion": settings.A2A_PROTOCOL_VERSION,
            }
        ],
        "provider": {"organization": settings.APP_NAME, "url": settings.A2A_PUBLIC_URL},
        "version": settings.APP_VERSION,
        # Everything below streaming is honestly false: this is the card +
        # synchronous SendMessage subset, nothing more.
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "extendedAgentCard": False,
        },
        "securitySchemes": {
            "agentToken": {
                "httpAuthSecurityScheme": {"scheme": "bearer"},
            }
        },
        "securityRequirements": [{"schemes": {"agentToken": {"list": []}}}],
        "defaultInputModes": TEXT_ONLY,
        "defaultOutputModes": TEXT_ONLY,
        "skills": _skills(agent, tools),
    }
