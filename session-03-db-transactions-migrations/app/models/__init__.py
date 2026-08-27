"""Importing every model here means Base.metadata knows about all tables.

Alembic imports this package, so a new model only needs to be added to this list
for autogenerate to pick it up.
"""

from app.models.enums import ProjectRole, TaskPriority, TaskStatus
from app.models.project import Project
from app.models.project_user import ProjectUser
from app.models.task import Task
from app.models.user import User

__all__ = [
    "Project",
    "ProjectRole",
    "ProjectUser",
    "Task",
    "TaskPriority",
    "TaskStatus",
    "User",
]
