"""Starts the web server and wires every router."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.middleware.cors import CORSMiddleware

from app.api import (
    a2a,
    agents,
    auth,
    chat_builder,
    connections,
    mcp_servers,
    models,
    notifications,
    runs,
    stats,
    team,
)
from app.config import settings
from app.db import async_session_factory, create_all
from app.dependencies.auth import ensure_demo_user
from app.exceptions.errors import AppException
from app.exceptions.handlers import (
    app_exception_handler,
    db_unavailable_handler,
    generic_exception_handler,
    validation_exception_handler,
)
from app.security.crypto import using_dev_key

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_all()
    async with async_session_factory() as session:
        await ensure_demo_user(session)
        # A restart is the moment to clear locks left by the previous process.
        from app.runtime.recovery import sweep

        await sweep(session)
    if using_dev_key():
        logger.warning(
            "CREDENTIAL_KEY is unset — using a derived dev key. Set it before production."
        )
    logger.info("model provider: %s", settings.MODEL_PROVIDER)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        debug=settings.DEBUG,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    from sqlalchemy.exc import DBAPIError, OperationalError, TimeoutError as PoolTimeout

    for db_error in (OperationalError, DBAPIError, PoolTimeout, ConnectionRefusedError):
        app.add_exception_handler(db_error, db_unavailable_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    for module in (
        a2a,
        agents,
        auth,
        runs,
        connections,
        mcp_servers,
        team,
        notifications,
        chat_builder,
        stats,
        models,
    ):
        app.include_router(module.router)

    @app.get("/health", tags=["System"])
    async def health():
        """503 if the database is unreachable; Redis absence is a downgrade, not a failure."""
        from fastapi.responses import JSONResponse
        from sqlalchemy import text

        from app.runtime.bus import get_redis

        db = "ok"
        try:
            async with async_session_factory() as session:
                await session.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            db = f"error: {type(exc).__name__}"

        from app.runtime.bus import redis_alive

        if await redis_alive():
            redis = "ok"
        elif settings.QUEUE_LOCAL_FALLBACK:
            redis = "fallback (in-process queues)"
        else:
            redis = "unreachable — runs cannot be queued"

        body = {
            "status": "ok" if db == "ok" and redis == "ok" else "degraded",
            "version": settings.APP_VERSION,
            "model_provider": settings.MODEL_PROVIDER,
            "builder_model": settings.BUILDER_MODEL,
            "db": db,
            "redis": redis,
            # The UI shows these instead of hard-coding them.
            "limits": {
                "max_attempts": settings.MAX_ATTEMPTS,
                "retry_backoff_seconds": settings.RETRY_BACKOFF_SECONDS,
                "run_timeout_seconds": settings.RUN_TIMEOUT_SECONDS,
                "max_tool_calls_per_run": settings.MAX_TOOL_CALLS_PER_RUN,
                "tool_call_timeout_seconds": settings.TOOL_CALL_TIMEOUT_SECONDS,
                "max_agents_per_user": settings.MAX_AGENTS_PER_USER,
            },
        }
        return JSONResponse(body, status_code=200 if db == "ok" else 503)

    return app


app = create_app()
