"""Common cross-domain enums."""

from enum import StrEnum


class Environment(StrEnum):
    """Runtime environment designations."""

    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"


class SortOrder(StrEnum):
    """Sort direction options for query pagination."""

    ASC = "asc"
    DESC = "desc"


class ImportStatus(StrEnum):
    """Lifecycle status designations for raw imports."""

    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
