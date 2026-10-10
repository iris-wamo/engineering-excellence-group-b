"""Role-based authorization (RBAC)
The matrix below is the single source of truth for what each role may do, and it mirrors
docs/rbac-authorization-matrix.md. Anything not listed for a role is denied.
"""

from collections.abc import Callable, Coroutine
from enum import StrEnum
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser
from app.core.exceptions import ForbiddenError, NotFoundError
from app.db.session import get_db
from app.models.enums import ProjectRole
from app.models.task import Task
from app.models.user import User
from app.repositories.membership_repository import MembershipRepository
from app.repositories.task_repository import TaskRepository


class Permission(StrEnum):
    """A single thing a role may be allowed to do."""

    project_create = "project_create"
    user_manage = "user_manage"
    task_assign = "task_assign"


ROLE_PERMISSIONS: dict[ProjectRole, set[Permission]] = {
    ProjectRole.admin: {
        Permission.project_create,
        Permission.user_manage,
        Permission.task_assign,
    },
    ProjectRole.manager: {Permission.task_assign},
    # "owner" predates RBAC and marks who owns a project; an owner may assign work
    # inside it, but may not create projects or manage users.
    ProjectRole.owner: {Permission.task_assign},
    # A member has no role-based permissions. They act on their own tasks only,
    # which is an ownership check rather than a role check (see require_task_assignee).
    ProjectRole.member: set(),
}


def role_allows(role: ProjectRole, permission: Permission) -> bool:
    """Return True when this role grants this permission."""
    return permission in ROLE_PERMISSIONS[role]


def require_permission(
    permission: Permission,
) -> Callable[[User, AsyncSession], Coroutine[Any, Any, User]]:
    """Build a dependency allowing the request only if any of the user's roles grants it"""

    async def dependency(
        current_user: CurrentUser,
        db: Annotated[AsyncSession, Depends(get_db)],
    ) -> User:
        roles = await MembershipRepository.get_all_roles(db, user_id=current_user.id)
        if not any(role_allows(role, permission) for role in roles):
            raise ForbiddenError()
        return current_user

    return dependency


def require_task_permission(
    permission: Permission,
) -> Callable[[int, User, AsyncSession], Coroutine[Any, Any, User]]:
    """Build a dependency checking the user's role in the project the task belongs to."""

    async def dependency(
        task_id: int,
        current_user: CurrentUser,
        db: Annotated[AsyncSession, Depends(get_db)],
    ) -> User:
        task = await _get_task(db, task_id)
        role = await MembershipRepository.get_role_in_project(
            db, user_id=current_user.id, project_id=task.project_id
        )
        if role is None or not role_allows(role, permission):
            raise ForbiddenError()
        return current_user

    return dependency


async def require_task_assignee(
    task_id: int,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Allow the request only if the task is assigned to the caller.

    This is deliberately an ownership check, not a role check: every role may move their
    own task's status, and no role may move someone else's.
    """
    task = await _get_task(db, task_id)
    if task.assignee_id != current_user.id:
        raise ForbiddenError("You can only update the status of tasks assigned to you")
    return current_user


async def _get_task(db: AsyncSession, task_id: int) -> Task:
    """Load the task an authorization check is about.

    Raises the same NotFoundError the task service uses, so a missing task still
    answers 404 and authorization does not change existing behavior.
    """
    task = await TaskRepository.get_by_id(db, task_id)
    if task is None:
        raise NotFoundError(
            "Task not found",
            details=[{"field": "task_id", "message": f"Task {task_id} does not exist"}],
        )
    return task
