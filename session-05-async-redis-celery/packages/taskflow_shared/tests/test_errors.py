"""Unit tests for taskflow_shared.errors."""

from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient
from taskflow_shared.contracts.constants import HEADER_REQUEST_ID
from taskflow_shared.errors import (
    ConflictError,
    DomainError,
    ErrorResponse,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationAppError,
    register_exception_handlers,
)
from taskflow_shared.logging import RequestIdMiddleware


def test_error_hierarchy_status_codes() -> None:
    """Verify default status codes and error codes across the AppError hierarchy."""
    assert NotFoundError("not found").status_code == status.HTTP_404_NOT_FOUND
    assert NotFoundError("not found").code == "NOT_FOUND"

    assert ConflictError("conflict").status_code == status.HTTP_409_CONFLICT
    assert ConflictError("conflict").code == "CONFLICT"

    assert ValidationAppError("validation").status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert ValidationAppError("validation").code == "VALIDATION_ERROR"

    assert UnauthorizedError("unauthorized").status_code == status.HTTP_401_UNAUTHORIZED
    assert UnauthorizedError("unauthorized").code == "UNAUTHORIZED"

    assert ForbiddenError("forbidden").status_code == status.HTTP_403_FORBIDDEN
    assert ForbiddenError("forbidden").code == "FORBIDDEN"

    assert DomainError("invalid state").status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert DomainError("invalid state").code == "DOMAIN_ERROR"


def test_exception_handlers_envelope() -> None:
    """Verify registered FastAPI handlers format responses matching ErrorResponse schema."""
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)

    @app.get("/trigger-app-error")
    def trigger_app_error() -> None:
        raise NotFoundError(
            "Project 42 not found",
            details=[{"field": "project_id", "message": "Does not exist"}],
        )

    @app.get("/trigger-domain-error")
    def trigger_domain_error() -> None:
        raise DomainError("Cannot transition from done to todo")

    @app.get("/trigger-auth-error")
    def trigger_auth_error() -> None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.get("/trigger-crash")
    def trigger_crash() -> None:
        raise RuntimeError("Simulated crash")

    client = TestClient(app, raise_server_exceptions=False)

    # 1. Test NotFoundError
    res404 = client.get("/trigger-app-error")
    assert res404.status_code == 404
    data404 = res404.json()
    validated404 = ErrorResponse.model_validate(data404)
    assert validated404.error.code == "NOT_FOUND"
    assert validated404.error.message == "Project 42 not found"
    assert validated404.error.details[0].field == "project_id"

    # 2. Test DomainError
    res422 = client.get("/trigger-domain-error")
    assert res422.status_code == 422
    data422 = res422.json()
    validated422 = ErrorResponse.model_validate(data422)
    assert validated422.error.code == "DOMAIN_ERROR"
    assert validated422.error.message == "Cannot transition from done to todo"

    # 3. Test unknown route (Starlette 404 routing error) returns ADR-001 envelope
    unknown_route_res = client.get("/does-not-exist")
    assert unknown_route_res.status_code == 404
    data_unknown = unknown_route_res.json()
    validated_unknown = ErrorResponse.model_validate(data_unknown)
    assert validated_unknown.error.code == "NOT_FOUND"
    assert validated_unknown.error.message == "Not Found"

    # 4. Test wrong method (Starlette 405 error) returns ADR-001 envelope and preserves Allow header
    wrong_method_res = client.post("/trigger-app-error")
    assert wrong_method_res.status_code == 405
    data_wrong_method = wrong_method_res.json()
    validated_wrong_method = ErrorResponse.model_validate(data_wrong_method)
    assert validated_wrong_method.error.code == "METHOD_NOT_ALLOWED"
    assert "Allow" in wrong_method_res.headers

    # 5. Test 401 preserves WWW-Authenticate header
    auth_res = client.get("/trigger-auth-error")
    assert auth_res.status_code == 401
    assert auth_res.headers.get("WWW-Authenticate") == "Bearer"
    validated_auth = ErrorResponse.model_validate(auth_res.json())
    assert validated_auth.error.code == "UNAUTHORIZED"

    # 6. Test 500 unhandled exception returns ADR-001 envelope and includes X-Request-ID
    crash_res = client.get("/trigger-crash")
    assert crash_res.status_code == 500
    assert HEADER_REQUEST_ID in crash_res.headers
    data_crash = crash_res.json()
    validated_crash = ErrorResponse.model_validate(data_crash)
    assert validated_crash.error.code == "INTERNAL_SERVER_ERROR"
