"""FastAPI and Starlette exception handlers mapping exceptions to ADR-001 envelopes."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from taskflow_shared.contracts.constants import HEADER_REQUEST_ID
from taskflow_shared.errors.exceptions import AppError
from taskflow_shared.errors.schemas import ErrorBody, ErrorDetail, ErrorResponse
from taskflow_shared.logging.context import get_request_id

logger = logging.getLogger(__name__)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Handle domain AppError instances and return standard envelope."""
    details = [
        ErrorDetail(field=d.get("field"), message=d.get("message", ""))
        for d in exc.details
        if isinstance(d, dict)
    ]
    body = ErrorResponse(
        error=ErrorBody(
            code=exc.code,
            message=exc.message,
            details=details,
        )
    )
    headers: dict[str, str] = {}
    request_id = get_request_id()
    if request_id:
        headers[HEADER_REQUEST_ID] = request_id

    return JSONResponse(
        status_code=exc.status_code,
        content=body.model_dump(),
        headers=headers or None,
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle FastAPI / Pydantic validation errors and format into standard envelope."""
    details: list[ErrorDetail] = []
    for error in exc.errors():
        loc = error.get("loc", ())
        field = ".".join(str(part) for part in loc if part not in ("body", "query", "path"))
        details.append(
            ErrorDetail(
                field=field or None,
                message=error.get("msg", "Invalid value"),
            )
        )

    body = ErrorResponse(
        error=ErrorBody(
            code="VALIDATION_ERROR",
            message="Request validation failed",
            details=details,
        )
    )
    headers: dict[str, str] = {}
    request_id = get_request_id()
    if request_id:
        headers[HEADER_REQUEST_ID] = request_id

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=body.model_dump(),
        headers=headers or None,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Handle standard Starlette and FastAPI HTTPExceptions."""
    code_map: dict[int, str] = {
        status.HTTP_400_BAD_REQUEST: "BAD_REQUEST",
        status.HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
        status.HTTP_403_FORBIDDEN: "FORBIDDEN",
        status.HTTP_404_NOT_FOUND: "NOT_FOUND",
        status.HTTP_405_METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
        status.HTTP_409_CONFLICT: "CONFLICT",
        status.HTTP_422_UNPROCESSABLE_CONTENT: "VALIDATION_ERROR",
        status.HTTP_429_TOO_MANY_REQUESTS: "TOO_MANY_REQUESTS",
    }
    code = code_map.get(exc.status_code, "HTTP_ERROR")

    details: list[ErrorDetail] = []
    if isinstance(exc.detail, str):
        message = exc.detail
    elif isinstance(exc.detail, dict):
        message = str(
            exc.detail.get("message") or exc.detail.get("detail") or "An HTTP error occurred"
        )
        details = [
            ErrorDetail(field=str(k), message=str(v))
            for k, v in exc.detail.items()
            if k not in ("message", "detail")
        ]
    elif isinstance(exc.detail, list):
        message = "An HTTP error occurred"
        for item in exc.detail:
            if isinstance(item, dict):
                details.append(
                    ErrorDetail(
                        field=str(item.get("field")) if item.get("field") is not None else None,
                        message=str(item.get("message", item.get("msg", ""))),
                    )
                )
            else:
                details.append(ErrorDetail(field=None, message=str(item)))
    else:
        message = str(exc.detail) if exc.detail else "An HTTP error occurred"

    body = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            details=details,
        )
    )

    response_headers = dict(getattr(exc, "headers", None) or {})
    request_id = get_request_id()
    if request_id and HEADER_REQUEST_ID not in response_headers:
        response_headers[HEADER_REQUEST_ID] = request_id

    return JSONResponse(
        status_code=exc.status_code,
        content=body.model_dump(),
        headers=response_headers or None,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled exceptions."""
    logger.exception("Unhandled exception: %s", exc)
    body = ErrorResponse(
        error=ErrorBody(
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected error occurred. Please try again later.",
            details=[],
        )
    )
    headers: dict[str, str] = {}
    request_id = get_request_id()
    if request_id:
        headers[HEADER_REQUEST_ID] = request_id

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=body.model_dump(),
        headers=headers or None,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register all standard exception handlers with a FastAPI application."""
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
