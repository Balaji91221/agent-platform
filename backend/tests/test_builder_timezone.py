"""The draft's schedule runs where the user is, not in UTC."""

from app.builder.draft import _coerce

RAW = {"intent": "draft", "name": "Digest", "description": "d", "system_prompt": "s",
       "user_prompt": "u", "cron": "0 9 * * 1-5", "timezone": "UTC", "tools": [], "model": "nemotron-3-super"}


def test_a_model_defaulting_to_utc_is_overridden_by_the_browser_zone():
    assert _coerce(dict(RAW), "Asia/Kolkata", "every weekday at 9am").timezone == "Asia/Kolkata"


def test_an_explicit_utc_request_is_kept():
    assert _coerce(dict(RAW), "Asia/Kolkata", "every day at 09:00 UTC").timezone == "UTC"


def test_a_named_zone_from_the_model_is_kept():
    raw = dict(RAW, timezone="Europe/Berlin")
    assert _coerce(raw, "Asia/Kolkata", "9am Berlin time").timezone == "Europe/Berlin"


def test_a_bogus_zone_falls_back_to_the_browser_zone():
    raw = dict(RAW, timezone="Mars/Olympus")
    assert _coerce(raw, "Asia/Kolkata", "x").timezone == "Asia/Kolkata"


def test_no_browser_zone_keeps_the_old_default():
    assert _coerce(dict(RAW, timezone=""), None, "x").timezone == "Asia/Kolkata"
