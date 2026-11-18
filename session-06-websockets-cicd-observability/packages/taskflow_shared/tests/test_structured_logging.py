"""Tests for JSON log records, bound log fields and redaction."""

import json
import logging
import sys
from collections.abc import Iterator

import pytest
from taskflow_shared.errors import NotFoundError
from taskflow_shared.logging import (
    JsonFormatter,
    RedactingFormatter,
    already_logged,
    bind_log_fields,
    clear_log_context,
    configure_logging,
    error_category,
    get_log_fields,
    mark_logged,
    redact,
    set_request_id,
    start_log_context,
)
from taskflow_shared.logging.formatters import REDACTED


@pytest.fixture(autouse=True)
def _clean_context() -> Iterator[None]:
    set_request_id(None)
    clear_log_context()
    yield
    set_request_id(None)
    clear_log_context()


def _format(message: str, *args: object, **extra: object) -> dict[str, object]:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, message, args, None)
    record.__dict__.update(extra)
    result: dict[str, object] = json.loads(JsonFormatter().format(record))
    return result


def test_json_record_has_core_fields_and_request_id() -> None:
    set_request_id("req-1")

    entry = _format("hello %s", "world")

    assert entry["message"] == "hello world"
    assert entry["level"] == "INFO"
    assert entry["logger"] == "app.test"
    assert entry["request_id"] == "req-1"
    assert str(entry["timestamp"]).endswith("+00:00")


def test_json_record_includes_bound_fields_and_extra() -> None:
    start_log_context()
    bind_log_fields(user_id=7, workspace_id=1)

    entry = _format("done", operation="GET /x", duration_ms=1.5)

    assert entry["user_id"] == 7
    assert entry["workspace_id"] == 1
    assert entry["operation"] == "GET /x"
    assert entry["duration_ms"] == 1.5


def test_extra_wins_over_a_bound_field_of_the_same_name() -> None:
    start_log_context()
    bind_log_fields(outcome="bound")

    assert _format("x", outcome="extra")["outcome"] == "extra"


def test_bind_outside_a_context_is_a_no_op() -> None:
    bind_log_fields(user_id=1)

    assert get_log_fields() == {}


def test_bind_skips_none_values() -> None:
    start_log_context()
    bind_log_fields(project_id=None, task_id=3)

    assert get_log_fields() == {"task_id": 3}


def test_fields_bound_in_place_are_visible_to_the_context_owner() -> None:
    fields = start_log_context()
    bind_log_fields(user_id=5)

    assert fields == {"user_id": 5}


def test_sensitive_keys_are_redacted_at_any_depth() -> None:
    data = {
        "password": "hunter2",
        "access_token": "abc",
        "headers": {"Authorization": "Bearer abc", "X-Api-Key": "k"},
        "items": [{"new_password": "p"}],
        "email": "a@example.com",
    }

    assert redact(data) == {
        "password": REDACTED,
        "access_token": REDACTED,
        "headers": {"Authorization": REDACTED, "X-Api-Key": REDACTED},
        "items": [{"new_password": REDACTED}],
        "email": "a@example.com",
    }


def test_credentials_in_the_message_are_masked() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl"

    entry = _format("login with Bearer %s then %s", "secret-value", jwt)

    assert "secret-value" not in str(entry["message"])
    assert jwt not in str(entry["message"])
    assert str(entry["message"]).count(REDACTED) == 2


def test_sensitive_extra_fields_are_redacted() -> None:
    entry = _format("signup", password="hunter2", token="abc")

    assert entry["password"] == REDACTED
    assert entry["token"] == REDACTED


def test_exception_type_and_traceback_are_included() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            "app.test", logging.ERROR, __file__, 1, "failed", None, sys.exc_info()
        )
    entry = json.loads(JsonFormatter().format(record))

    assert entry["exc_type"] == "ValueError"
    assert "boom" in entry["exc_info"]


def test_configure_logging_json_style_uses_the_json_formatter() -> None:
    configure_logging(style="json")
    try:
        root = logging.getLogger()
        assert isinstance(root.handlers[0].formatter, JsonFormatter)
        assert logging.getLogger("uvicorn.access").disabled
    finally:
        configure_logging()
        logging.getLogger("uvicorn.access").disabled = False


def test_text_format_masks_credentials_in_message_and_traceback() -> None:
    formatter = RedactingFormatter(logging.Formatter("%(message)s"))
    try:
        raise ValueError("header was Bearer abc.def")
    except ValueError:
        record = logging.LogRecord(
            "app.test", logging.ERROR, __file__, 1, "token Bearer xyz", None, sys.exc_info()
        )

    output = formatter.format(record)

    assert "xyz" not in output and "abc.def" not in output
    assert REDACTED in output


def test_configure_logging_accepts_lower_case_level_names() -> None:
    configure_logging(level="debug")
    try:
        assert logging.getLogger().level == logging.DEBUG
    finally:
        configure_logging()


@pytest.mark.parametrize(
    ("exc", "category"),
    [
        (NotFoundError("missing"), "not_found"),
        (ConnectionError(), "connection_error"),
        (TimeoutError(), "timeout_error"),
        (type("HTTPStatusError", (Exception,), {})(), "http_status_error"),
        (type("gaierror", (Exception,), {})(), "gaierror"),
        # Only AppErrors' codes count; other libraries use `code` for other things
        (type("CodedLibraryError", (Exception,), {"code": "gkpj"})(), "coded_library_error"),
    ],
)
def test_error_category_is_the_code_or_the_snake_case_class_name(
    exc: BaseException, category: str
) -> None:
    assert error_category(exc) == category


def test_exceptions_can_be_marked_as_logged() -> None:
    exc = RuntimeError()
    assert not already_logged(exc)

    mark_logged(exc)

    assert already_logged(exc)
