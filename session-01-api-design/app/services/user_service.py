from sqlalchemy.orm import Session

from app.core.exceptions import UserNotFoundError
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate


class UserService:
    @staticmethod
    def create_user(db: Session, payload: UserCreate) -> User:
        return UserRepository.create(db, name=payload.name, email=str(payload.email))

    @staticmethod
    def get_users(db: Session, *, limit: int = 10, offset: int = 0) -> list[User]:
        return UserRepository.get_all(db, limit=limit, offset=offset)

    @staticmethod
    def get_user(db: Session, user_id: int) -> User:
        user = UserRepository.get_by_id(db, user_id)
        if user is None:
            raise UserNotFoundError()

        return user
