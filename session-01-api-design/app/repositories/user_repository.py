from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import EmailAlreadyExistsError
from app.models.user import User


class UserRepository:
    @staticmethod
    def create(db: Session, *, name: str, email: str) -> User:
        user = User(name=name, email=email)
        try:
            db.add(user)
            db.commit()
            db.refresh(user)
            return user
        except IntegrityError:
            db.rollback()
            raise EmailAlreadyExistsError() from None

    @staticmethod
    def get_all(db: Session, *, limit: int = 10, offset: int = 0) -> list[User]:
        result = db.execute(select(User).order_by(User.id).limit(limit).offset(offset))
        return list(result.scalars().all())

    @staticmethod
    def get_by_id(db: Session, user_id: int) -> User | None:
        result = db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    @staticmethod
    def get_by_email(db: Session, email: str) -> User | None:
        result = db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()
