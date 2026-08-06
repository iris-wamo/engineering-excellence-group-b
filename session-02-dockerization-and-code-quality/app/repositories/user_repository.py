from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EmailAlreadyExistsError
from app.models.user import User


class UserRepository:
    @staticmethod
    async def create(db: AsyncSession, *, name: str, email: str) -> User:
        user = User(name=name, email=email)
        try:
            db.add(user)
            await db.commit()
            await db.refresh(user)
            return user
        except IntegrityError:
            await db.rollback()
            raise EmailAlreadyExistsError() from None

    @staticmethod
    async def get_all(db: AsyncSession, *, limit: int, offset: int) -> tuple[list[User], int]:
        total = await db.scalar(select(func.count()).select_from(User)) or 0

        users = (await db.scalars(select(User).order_by(User.id).offset(offset).limit(limit))).all()

        return list(users), total

    @staticmethod
    async def get_by_id(db: AsyncSession, user_id: int) -> User | None:
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_email(db: AsyncSession, email: str) -> User | None:
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()
