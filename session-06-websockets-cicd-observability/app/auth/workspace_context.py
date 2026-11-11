"""Workspace context dependency and multi-tenant authorization."""

from typing import Annotated

from fastapi import Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession
from taskflow_shared.contracts.constants import HEADER_WORKSPACE_ID

from app.auth.dependencies import OptionalCurrentUser
from app.core.config import settings
from app.core.exceptions import AppError, ForbiddenError, NotAuthenticatedError, NotFoundError
from app.db.session import get_db
from app.repositories.workspace_repository import WorkspaceRepository


class InvalidWorkspaceHeaderError(AppError):
    """Raised when the X-Workspace-ID header cannot be parsed as a positive integer."""

    code = "INVALID_WORKSPACE_ID"
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(
        self,
        message: str = "Invalid X-Workspace-ID header format. Must be a positive integer.",
    ) -> None:
        super().__init__(message)


async def get_current_workspace_id(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: OptionalCurrentUser,
    workspace_header: Annotated[str | None, Header(alias=HEADER_WORKSPACE_ID)] = None,
) -> int:
    """Extract and validate the active workspace ID for the request.

    Rules:
    1. If X-Workspace-ID is provided:
       - Must be a valid positive integer (raises 400 InvalidWorkspaceHeaderError).
       - The workspace must exist in the database (raises 404 NotFoundError).
       - If user is authenticated: user must be a member of this workspace
         (raises 403 ForbiddenError).
       - If user is NOT authenticated: raises 401 NotAuthenticatedError.
       - Returns the validated integer workspace ID.
    2. If X-Workspace-ID is omitted:
       - Defaults to 1 (Default Workspace for backward compatibility).
       - If user is authenticated and not yet in workspace 1, ensures enrollment.
       - Returns 1.
    """
    if workspace_header is not None:
        try:
            workspace_id = int(workspace_header.strip())
            if workspace_id <= 0:
                raise ValueError()
        except ValueError:
            raise InvalidWorkspaceHeaderError() from None

        if user is None:
            raise NotAuthenticatedError()

        workspace = await WorkspaceRepository.get_by_id(db, workspace_id)
        if workspace is None:
            raise NotFoundError(
                "Workspace not found",
                details=[
                    {
                        "field": "workspace_id",
                        "message": f"Workspace {workspace_id} does not exist",
                    }
                ],
            )

        is_member = await WorkspaceRepository.is_user_in_workspace(
            db, workspace_id=workspace_id, user_id=user.id
        )
        if not is_member:
            raise ForbiddenError("You do not have permission to access this workspace")

        return workspace_id

    # Fallback to default workspace context when X-Workspace-ID is omitted
    if user is not None:
        user_workspaces = await WorkspaceRepository.get_user_workspaces(db, user.id)
        if not user_workspaces:
            raise ForbiddenError("You do not have permission to access any workspace")

        if any(ws.id == 1 for ws in user_workspaces):
            return 1

    if not settings.allow_anonymous_default_workspace:
        raise NotAuthenticatedError()

    return 1


CurrentWorkspaceId = Annotated[int, Depends(get_current_workspace_id)]
