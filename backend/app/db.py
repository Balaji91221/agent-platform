"""Database engine and session factory."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


# pool_pre_ping: a request cancelled mid-query (browser closed the SSE stream)
# leaves a dead asyncpg connection in the pool; ping before reuse instead of
# handing it to the next request as a 500.
_pool = {} if settings.DATABASE_URL.startswith("sqlite") else {"pool_size": 10, "max_overflow": 20}
engine = create_async_engine(
    settings.DATABASE_URL, echo=False, future=True, pool_pre_ping=True, **_pool
)

async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """A session whose close always completes.

    When the browser drops a request, uvicorn cancels the task and the
    cancellation also lands inside `session.close()`, so the connection was
    never checked back in ("garbage collector is trying to clean up
    non-checked-in connection"). Shielding the close lets it finish as its
    own task while the request itself still stops.
    """
    session = async_session_factory()
    try:
        yield session
    except Exception:
        await asyncio.shield(session.rollback())
        raise
    finally:
        await asyncio.shield(session.close())


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with session_scope() as session:
        yield session


async def create_all() -> None:
    """Dev convenience. Production uses Alembic migrations."""
    import app.models  # noqa: F401  (registers every table on Base.metadata)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
