"""Shared StrEnum types backed by native Postgres ENUM columns."""

from enum import StrEnum


class TaskStatus(StrEnum):
    todo = "todo"
    in_progress = "in_progress"
    done = "done"


class TaskPriority(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class ProjectRole(StrEnum):
    """A user's role within a single project. See docs/rbac-authorization-matrix.md."""

    admin = "admin"
    manager = "manager"
    owner = "owner"
    member = "member"
