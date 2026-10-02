"""Business logic for user management."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UserNotFoundError
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate


class UserService:
    @staticmethod
    async def create_user(db: AsyncSession, payload: UserCreate) -> User:
        return await UserRepository.create(db, name=payload.name, email=str(payload.email))

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
