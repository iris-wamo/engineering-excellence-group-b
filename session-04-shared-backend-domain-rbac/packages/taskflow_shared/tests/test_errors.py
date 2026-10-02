"""Unit tests for taskflow_shared.errors."""

from fastapi import FastAPI, status
from fastapi.testclient import TestClient
from taskflow_shared.errors import (
    ConflictError,
    DomainError,
    EmailAlreadyExistsError,
    ErrorResponse,
    ForbiddenError,
    NotFoundError,
    ProjectMembershipRequiredError,
    TransactionSimulationError,
    UnauthorizedError,
    UserNotFoundError,
    ValidationAppError,
    register_exception_handlers,
)


def test_error_hierarchy_status_codes() -> None:
    """Verify default status codes and error codes across the AppError hierarchy."""
    assert NotFoundError("not found").status_code == status.HTTP_404_NOT_FOUND
    assert NotFoundError("not found").code == "NOT_FOUND"

    assert ConflictError("conflict").status_code == status.HTTP_409_CONFLICT
    assert ConflictError("conflict").code == "CONFLICT"

    assert ValidationAppError("validation").status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert ValidationAppError("validation").code == "VALIDATION_ERROR"

    assert UnauthorizedError("unauthorized").status_code == status.HTTP_401_UNAUTHORIZED
    assert UnauthorizedError("unauthorized").code == "UNAUTHORIZED"

    assert ForbiddenError("forbidden").status_code == status.HTTP_403_FORBIDDEN
    assert ForbiddenError("forbidden").code == "FORBIDDEN"

    assert DomainError("invalid state").status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert DomainError("invalid state").code == "DOMAIN_ERROR"

    assert EmailAlreadyExistsError().status_code == status.HTTP_409_CONFLICT
    assert EmailAlreadyExistsError().code == "CONFLICT"

    assert UserNotFoundError().status_code == status.HTTP_404_NOT_FOUND
    assert UserNotFoundError().code == "NOT_FOUND"

    membership_err = ProjectMembershipRequiredError(user_id=1, project_id=2)
    assert membership_err.status_code == status.HTTP_400_BAD_REQUEST
    assert membership_err.code == "PROJECT_MEMBERSHIP_REQUIRED"
    assert membership_err.details[0]["field"] == "assignee_id"

    tx_err = TransactionSimulationError("Simulated failure")
    assert tx_err.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert tx_err.code == "SIMULATED_TRANSACTION_FAILURE"


def test_exception_handlers_envelope() -> None:
    """Verify registered FastAPI handlers format responses matching ErrorResponse schema."""
    app = FastAPI()
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

    client = TestClient(app)

    # Test NotFoundError
    res404 = client.get("/trigger-app-error")
    assert res404.status_code == 404
    data404 = res404.json()
    validated404 = ErrorResponse.model_validate(data404)
    assert validated404.error.code == "NOT_FOUND"
    assert validated404.error.message == "Project 42 not found"
    assert validated404.error.details[0].field == "project_id"

    # Test DomainError
    res422 = client.get("/trigger-domain-error")
    assert res422.status_code == 422
    data422 = res422.json()
    validated422 = ErrorResponse.model_validate(data422)
    assert validated422.error.code == "DOMAIN_ERROR"
    assert validated422.error.message == "Cannot transition from done to todo"
