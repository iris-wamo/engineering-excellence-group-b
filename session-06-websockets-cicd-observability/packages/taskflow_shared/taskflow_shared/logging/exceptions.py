"""Helpers for logging exceptions consistently across the API and workers."""

import re

_LOGGED_ATTR = "_taskflow_logged"
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def error_category(exc: BaseException) -> str:
    """snake_case category: the error envelope code for AppErrors, else the class name.

    NotFoundError -> not_found (its code), ConnectionError -> connection_error.
    """
    code = getattr(exc, "code", None)
    name = code if isinstance(code, str) else type(exc).__name__
    return _CAMEL_BOUNDARY.sub("_", name).lower()


def mark_logged(exc: BaseException) -> None:
    """Record that the traceback was already logged, so outer handlers skip it."""
    setattr(exc, _LOGGED_ATTR, True)


def already_logged(exc: BaseException) -> bool:
    return getattr(exc, _LOGGED_ATTR, False) is True
