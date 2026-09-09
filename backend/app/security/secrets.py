"""What sits inside a credential's ciphertext.

A pasted API key is stored as the raw string. An OAuth connection stores a JSON
blob `{"access_token", "refresh_token", "expires_at"}` so the refresh token
survives next to the access token. Connectors only ever need `access_token()`.
"""

from __future__ import annotations

import json


def parse_secret(raw: str | None) -> dict:
    if not raw:
        return {}
    if raw.lstrip().startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "access_token" in data:
                return data
        except ValueError:
            pass
    return {"access_token": raw}


def access_token(raw: str | None) -> str | None:
    return parse_secret(raw).get("access_token") or None


def dump_secret(access_token: str, refresh_token: str | None, expires_at: str | None) -> str:
    return json.dumps(
        {"access_token": access_token, "refresh_token": refresh_token, "expires_at": expires_at}
    )
