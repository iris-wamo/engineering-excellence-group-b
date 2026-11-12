"""Factory-style helpers that insert ready-to-use rows for tests.

Each method fills in sensible, unique defaults so a test only spells out what it cares
about:

    owner = await factory.user()
    project = await factory.project()
    await factory.grant_role(owner, project, ProjectRole.owner)
    task = await factory.task(project, assignee=owner, status=TaskStatus.review)

Rows are written straight to the database, skipping services and RBAC. That is what
lets a test set up state the API would refuse to create (an admin before any admin
exists, a task already in `review`, a user outside every workspace). Use the API in
the test body itself whenever the behavior under test is the API.
"""

from collections.abc import Iterable
from datetime import date
from itertools import count
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password
from app.db.base import Base
from app.models.enums import ProjectRole, TaskPriority, TaskStatus
from app.models.project import Project
from app.models.project_user import ProjectUser
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_user import WorkspaceUser
from tests.fixtures.auth import AuthedUser, auth_headers_for

DEFAULT_WORKSPACE_ID = 1

# An id no factory will reach within a test, for not-found cases.
MISSING_ID = 999_900_000

ModelT = TypeVar("ModelT", bound=Base)


class DataFactory:
    """Creates users, workspaces, projects, roles, and tasks inside one test session."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._seq = count(1)

    def _next(self) -> int:
        return next(self._seq)

    async def _save(self, row: ModelT) -> ModelT:
        # Commit, not just flush: db_session turns commits into savepoints, and code under
        # test that calls rollback() only undoes its own work, never this setup row.
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def workspace(self, *, name: str | None = None, slug: str | None = None) -> Workspace:
        """A new tenant workspace with no members."""
        n = self._next()
        return await self._save(
            Workspace(name=name or f"Workspace {n}", slug=slug or f"workspace-{n}")
        )

    async def user(
        self,
        *,
        name: str | None = None,
        email: str | None = None,
        password: str | None = None,
        is_active: bool = True,
        workspace_ids: Iterable[int] = (DEFAULT_WORKSPACE_ID,),
    ) -> User:
        """A user enrolled in the given workspaces (Workspace 1 by default, like signup).

        No password is stored unless one is passed, because hashing is slow and most
        tests authenticate with a minted token instead of logging in. Pass
        `workspace_ids=()` for a user who belongs to no workspace.
        """
        n = self._next()
        user = await self._save(
            User(
                name=name or f"User {n}",
                email=email or f"user-{n}@factory.test",
                password_hash=hash_password(password) if password is not None else None,
                is_active=is_active,
            )
        )
        for workspace_id in dict.fromkeys(workspace_ids):
            await self.add_to_workspace(user, workspace_id)
        return user

    async def add_to_workspace(self, user: User | int, workspace: Workspace | int) -> WorkspaceUser:
        """Make the user (a User or a user id) a member of a workspace."""
        user_id = user.id if isinstance(user, User) else user
        workspace_id = workspace if isinstance(workspace, int) else workspace.id
        return await self._save(WorkspaceUser(workspace_id=workspace_id, user_id=user_id))

    async def project(
        self,
        *,
        name: str | None = None,
        slug: str | None = None,
        workspace: Workspace | int = DEFAULT_WORKSPACE_ID,
        description: str | None = None,
    ) -> Project:
        """A project in the given workspace (Workspace 1 by default)."""
        n = self._next()
        workspace_id = workspace if isinstance(workspace, int) else workspace.id
        return await self._save(
            Project(
                name=name or f"Project {n}",
                slug=slug or f"project-{n}",
                description=description,
                workspace_id=workspace_id,
            )
        )

    async def grant_role(
        self, user: User | int, project: Project, role: ProjectRole
    ) -> ProjectUser:
        """Give the user (a User or a user id) a role in the project.

        This is also what makes them a project member.
        """
        user_id = user.id if isinstance(user, User) else user
        return await self._save(ProjectUser(project_id=project.id, user_id=user_id, role=role))

    async def task(
        self,
        project: Project,
        *,
        title: str | None = None,
        assignee: User | int | None = None,
        status: TaskStatus = TaskStatus.todo,
        priority: TaskPriority = TaskPriority.medium,
        description: str | None = None,
        due_date: date | None = None,
    ) -> Task:
        """A task in the project, in the project's workspace.

        `status` is written directly, so a test can start from any point in the
        workflow without walking through the transitions first. `assignee` takes a
        User or a user id (such as `AuthedUser.id`).
        """
        n = self._next()
        return await self._save(
            Task(
                title=title or f"Task {n}",
                description=description,
                project_id=project.id,
                workspace_id=project.workspace_id,
                assignee_id=assignee.id if isinstance(assignee, User) else assignee,
                status=status,
                priority=priority,
                due_date=due_date,
            )
        )

    async def member(
        self,
        project: Project,
        role: ProjectRole = ProjectRole.member,
        *,
        name: str | None = None,
        email: str | None = None,
    ) -> AuthedUser:
        """A user in the project's workspace holding `role` in the project, ready to call the API.

        The returned headers carry both the bearer token and X-Workspace-ID for the
        project's workspace.
        """
        user = await self.user(name=name, email=email, workspace_ids=(project.workspace_id,))
        await self.grant_role(user, project, role)
        return AuthedUser(
            id=user.id, headers=auth_headers_for(user.id, workspace_id=project.workspace_id)
        )
