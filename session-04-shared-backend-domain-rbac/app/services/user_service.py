"""Business logic for user management."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UserNotFoundError
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_user import WorkspaceUser
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate


class UserService:
    @staticmethod
    async def create_user(db: AsyncSession, payload: UserCreate, workspace_id: int = 1) -> User:
        user = await UserRepository.create(db, name=payload.name, email=str(payload.email))
        ws = await db.get(Workspace, workspace_id)
        if ws is not None:
            db.add(WorkspaceUser(workspace_id=workspace_id, user_id=user.id))
            await db.commit()
            await db.refresh(user)
        return user

    @staticmethod
    async def get_users(db: AsyncSession, *, page: int, page_size: int) -> tuple[list[User], int]:
        offset = (page - 1) * page_size
        return await UserRepository.get_all(db, limit=page_size, offset=offset)

    @staticmethod
    async def get_user(db: AsyncSession, user_id: int) -> User:
        user = await UserRepository.get_by_id(db, user_id)
        if user is None:
            raise UserNotFoundError()

        return user
