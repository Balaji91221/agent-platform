"""One exception family; the handlers turn them into JSON (skill §11)."""

from enum import Enum


class ErrorCode(str, Enum):
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    LIMIT_REACHED = "LIMIT_REACHED"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppException(Exception):
    def __init__(self, message: str, code: ErrorCode, status_code: int = 500):
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class NotFoundException(AppException):
    def __init__(self, entity: str = "Resource", identifier: object = None):
        msg = f"{entity} not found" + (f" (id={identifier})" if identifier is not None else "")
        super().__init__(msg, ErrorCode.NOT_FOUND, 404)


class ConflictException(AppException):
    """Plan NFR-4 — a run requested while one is already in progress."""

    def __init__(self, message: str = "Already in progress"):
        super().__init__(message, ErrorCode.CONFLICT, 409)


class LimitReachedException(AppException):
    """Plan §5 — the 5-agent cap answers 402, not 400."""

    def __init__(self, message: str):
        super().__init__(message, ErrorCode.LIMIT_REACHED, 402)


class ValidationException(AppException):
    def __init__(self, message: str = "Validation failed"):
        super().__init__(message, ErrorCode.VALIDATION_ERROR, 422)


class UpstreamException(AppException):
    """A provider or server outside this app failed. `retryable` is False for a
    request the provider rejected outright — sending it again cannot help."""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message, ErrorCode.UPSTREAM_ERROR, 502)
        self.retryable = retryable


class UnauthorizedException(AppException):
    """No valid session. The frontend sends the browser to /login on this."""

    def __init__(self, message: str = "Sign in to continue"):
        super().__init__(message, ErrorCode.UNAUTHORIZED, status_code=401)
