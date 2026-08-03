from sqlalchemy import func, select
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
    def get_all(db: Session, *, limit: int, offset: int) -> tuple[list[User], int]:
        total = db.scalar(select(func.count()).select_from(User)) or 0

        users = db.scalars(select(User).order_by(User.id).offset(offset).limit(limit)).all()

        return list(users), total

    @staticmethod
    def get_by_id(db: Session, user_id: int) -> User | None:
        result = db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    @staticmethod
    def get_by_email(db: Session, email: str) -> User | None:
        result = db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()
