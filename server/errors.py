"""
Centralized error handling for the Robot Session Recording API.

- API consumers get clean, human-friendly JSON error responses
- Server logs get full detail (stack traces, context) for debugging
- Controlled by ROBOT_DEBUG env var: when True, stack traces are included in responses
"""

import logging
import traceback
from typing import Optional

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from server.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exception hierarchy
# ---------------------------------------------------------------------------

class AppError(Exception):
    """Base exception for all application errors."""

    def __init__(self, message: str, *, status_code: int = 500, detail: Optional[str] = None):
        self.message = message          # Human-friendly message for API consumers
        self.status_code = status_code
        self.detail = detail            # Extra context for server logs only
        super().__init__(message)


class NotFoundError(AppError):
    """Resource not found."""

    def __init__(self, resource: str, identifier: str = ""):
        msg = f"{resource} not found" + (f": {identifier}" if identifier else "")
        super().__init__(msg, status_code=404)


class ValidationError(AppError):
    """Invalid input from the client."""

    def __init__(self, message: str):
        super().__init__(message, status_code=422)


class DatabaseError(AppError):
    """Database operation failed."""

    def __init__(self, message: str = "A database error occurred", detail: Optional[str] = None):
        super().__init__(message, status_code=500, detail=detail)


class ExternalServiceError(AppError):
    """External API call failed (e.g. OpenAI)."""

    def __init__(self, service: str, message: str = "", detail: Optional[str] = None):
        msg = f"{service} service error" + (f": {message}" if message else "")
        super().__init__(msg, status_code=502, detail=detail)


class ImageStoreError(AppError):
    """Image storage operation failed."""

    def __init__(self, message: str = "Image storage error", detail: Optional[str] = None):
        super().__init__(message, status_code=500, detail=detail)


# ---------------------------------------------------------------------------
# Response builder
# ---------------------------------------------------------------------------

def _build_error_response(status_code: int, message: str, exc: Optional[Exception] = None) -> JSONResponse:
    """Build a consistent JSON error response."""
    body: dict = {
        "error": True,
        "status_code": status_code,
        "message": message,
    }
    if settings.debug and exc is not None:
        body["traceback"] = traceback.format_exception(type(exc), exc, exc.__traceback__)
    return JSONResponse(status_code=status_code, content=body)


# ---------------------------------------------------------------------------
# Global exception handlers — register on FastAPI app
# ---------------------------------------------------------------------------

def register_error_handlers(app: FastAPI) -> None:
    """Attach all global exception handlers to the FastAPI app."""

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        # Log with full context server-side
        if exc.status_code >= 500:
            logger.error(
                "%s (status=%d) detail=%s",
                exc.message, exc.status_code, exc.detail,
                exc_info=True,
            )
        else:
            logger.warning("%s (status=%d)", exc.message, exc.status_code)
        return _build_error_response(exc.status_code, exc.message, exc)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Catches FastAPI's own HTTPException (404s from routes, 422 from validation, etc.)
        logger.warning("HTTP %d: %s", exc.status_code, exc.detail)
        message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return _build_error_response(exc.status_code, message, exc)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        # Catch-all: log full traceback, return generic message to client
        logger.exception("Unhandled exception: %s", exc)
        message = "An unexpected error occurred. Please try again later."
        return _build_error_response(500, message, exc)


# ---------------------------------------------------------------------------
# WebSocket error helper
# ---------------------------------------------------------------------------

async def send_ws_error(ws: WebSocket, message: str, code: str = "error") -> None:
    """Send a structured error message to a WebSocket client."""
    try:
        await ws.send_json({"type": "error", "code": code, "message": message})
    except Exception:
        pass  # Connection already dead
