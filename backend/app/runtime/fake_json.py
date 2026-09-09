"""Schema-shaped placeholder data for the fake provider."""

from typing import Any


def fake_for_schema(schema: dict[str, Any], prompt: str) -> dict[str, Any]:
    props: dict[str, Any] = schema.get("properties", {})
    required: list[str] = schema.get("required", list(props))
    out: dict[str, Any] = {}

    for key in required:
        spec = props.get(key, {})
        out[key] = _value_for(key, spec, prompt)
    return out


def _value_for(key: str, spec: dict[str, Any], prompt: str) -> Any:
    if "enum" in spec:
        return spec["enum"][0]

    kind = spec.get("type", "string")
    if kind == "integer":
        return 0
    if kind == "number":
        return 0.0
    if kind == "boolean":
        return False
    if kind == "array":
        if key == "tools":
            return _guess_tools(prompt)
        return []
    if kind == "object":
        return fake_for_schema(spec, prompt)

    # Strings: echo the request where it makes the draft readable.
    lowered = key.lower()
    if "name" in lowered:
        return prompt.strip()[:40] or "New agent"
    if key == "reply":
        return ""
    if "reason" in lowered:
        return "Closest match to the request."
    if "description" in lowered or "prompt" in lowered:
        return prompt.strip()[:200]
    if "cron" in lowered:
        return "0 9 * * *"
    if "timezone" in lowered:
        return "Asia/Kolkata"
    return ""


_TOOL_HINTS = [
    (("inbox", "mail", "email"), "gmail.list_unread"),
    (("slack", "channel", "post"), "slack.post_message"),
    (("invoice", "stripe", "billing", "api", "endpoint"), "http.get"),
]


def _guess_tools(prompt: str) -> list[str]:
    """Pick the built-in tools the request seems to need."""
    lowered = prompt.lower()
    return [tool for words, tool in _TOOL_HINTS if any(w in lowered for w in words)]
