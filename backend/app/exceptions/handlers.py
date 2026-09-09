import logging

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.exceptions.errors import AppException, ErrorCode

logger = logging.getLogger(__name__)


async def app_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppException)
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": {"code": exc.code.value, "message": exc.message}},
    )


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": {
                "code": ErrorCode.VALIDATION_ERROR.value,
                "message": _first_problem(exc),
                # A validator's ValueError lands in ctx; encode it or the 422 itself 500s.
                "details": jsonable_encoder(exc.errors(), custom_encoder={Exception: str}),
            },
        },
    )


def _first_problem(exc: RequestValidationError) -> str:
    """One readable line for the UI: 'quiet_from: must be HH:MM, 24-hour'."""
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()) if p != "body")
        msg = str(err.get("msg", "")).removeprefix("Value error, ")
        return f"{loc}: {msg}" if loc else msg
    return "Request validation failed"


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s", request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": {"code": ErrorCode.INTERNAL_ERROR.value, "message": "Internal server error"},
        },
    )


async def db_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    """Postgres is down or refusing connections: a clean 503, not a traceback."""
    logger.error("database unavailable on %s: %s", request.url.path, type(exc).__name__)
    return JSONResponse(
        status_code=503,
        content={
            "success": False,
            "error": {
                "code": "DB_UNAVAILABLE",
                "message": "The database is unavailable right now; try again shortly.",
            },
        },
    )
