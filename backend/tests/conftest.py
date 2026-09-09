import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_agent_platform.db")
os.environ.setdefault("MODEL_PROVIDER", "fake")
# Model names that belong to NVIDIA route to the real API even under "fake",
# so the builder and lead are pinned to names the fake provider answers for.
os.environ.setdefault("BUILDER_MODEL", "claude-sonnet-5")
os.environ.setdefault("LEAD_MODEL", "claude-haiku-4.5")
os.environ.setdefault("BUILDER_FALLBACK_MODELS", "[]")
# Connectors answer with canned data and need no connection. Live-path tests
# flip this off and route httpx through a MockTransport.
os.environ.setdefault("CONNECTOR_STUBS", "true")
# The developer's .env may carry real OAuth clients and senders; tests assume none.
for _key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "SLACK_CLIENT_ID", "SLACK_CLIENT_SECRET",
             "GOOGLE_REDIRECT_URI", "NOTIFY_EMAIL", "YOUTUBE_API_KEY", "SMTP_HOST"):
    os.environ[_key] = ""
os.environ["EMAIL_SENDER"] = "console"
os.environ["AUTH_MODE"] = "demo"
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6399/0")  # unused port -> local queues
os.environ.setdefault("QUEUE_LOCAL_FALLBACK", "true")


@pytest.fixture(autouse=True)
def drain_queues():
    """The in-process queues are module-level; empty them between tests."""
    from app.runtime import bus

    bus._local_queues.clear()
    bus._local_subscribers.clear()
    yield
    bus._local_queues.clear()
    bus._local_subscribers.clear()


@pytest.fixture(autouse=True)
async def dispose_engine_after_each_test():
    """Any test that touches the app opens pooled asyncpg connections bound to
    its own event loop; the next test gets a new loop. Dispose unconditionally
    so no test order can leak a connection across loops."""
    yield
    from app.db import engine

    await engine.dispose()


@pytest.fixture
async def session():
    """A clean schema per test.

    The engine is disposed at the end of every test: its connection pool binds
    to the event loop that created it, and pytest gives each test a new loop.
    asyncpg raises on the mismatch (SQLite silently tolerates it), so disposing
    is what lets the same suite run on Postgres and SQLite alike.
    """
    from app.db import Base, async_session_factory, engine
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as s:
        yield s

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def user(session):
    from app.models import NotificationPref, User

    u = User(email="test@example.com")
    session.add(u)
    await session.commit()
    await session.refresh(u)
    session.add(NotificationPref(user_id=u.id))
    await session.commit()
    return u
