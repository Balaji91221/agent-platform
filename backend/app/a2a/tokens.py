"""A per-agent bearer token for A2A callers.

Derived, not stored: HMAC-SHA256 of the agent id under `CREDENTIAL_KEY`, the
same construction `security/session.py` uses for the session cookie. That means
no migration and no secret at rest — and rotating `CREDENTIAL_KEY` revokes every
agent's token at once, which is the only revocation story a derived token has.
"""

from __future__ import annotations

import hashlib
import hmac

from app.config import settings

_DEV_SEED = "agent-platform-dev-only-key"


def _key() -> bytes:
    # The `|a2a` suffix keeps these tokens from ever colliding with a session
    # signature, which is derived from the same secret.
    return hashlib.sha256((settings.CREDENTIAL_KEY or _DEV_SEED).encode() + b"|a2a").digest()


def issue(agent_id: int) -> str:
    return hmac.new(_key(), str(agent_id).encode(), hashlib.sha256).hexdigest()


def verify(agent_id: int, presented: str | None) -> bool:
    """Constant-time compare, so a wrong token leaks nothing through timing."""
    if not presented:
        return False
    return hmac.compare_digest(issue(agent_id), presented.strip())
