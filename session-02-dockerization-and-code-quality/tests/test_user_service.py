import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate
from app.services.user_service import UserService


def test_create_user_success(db_session: Session) -> None:
    payload = UserCreate(name="User", email="user@example.com")

    created = UserService.create_user(db_session, payload)

    assert created.id is not None
    assert created.name == payload.name
    assert created.email == str(payload.email)
    assert created.is_active is True


def test_create_user_rejects_duplicate_emails(db_session: Session) -> None:
    payload = UserCreate(name="User", email="user@example.com")

    UserService.create_user(db_session, payload)

    with pytest.raises(ConflictError) as exc_info:
        UserService.create_user(db_session, payload)

    assert exc_info.value.status_code == 409
    assert exc_info.value.message == "Email already exists"


def test_create_user_rejects_duplicate_emails_differing_by_case(db_session: Session) -> None:
    UserService.create_user(db_session, UserCreate(name="User", email="user@example.com"))

    with pytest.raises(ConflictError) as exc_info:
        UserService.create_user(db_session, UserCreate(name="User", email="USER@EXAMPLE.COM"))

    assert exc_info.value.status_code == 409


def test_get_users_returns_empty_list_when_no_users_exist(db_session: Session) -> None:
    users, total = UserService.get_users(db_session, page=1, page_size=10)

    assert users == []
    assert total == 0


def test_get_users_supports_pagination(db_session: Session) -> None:
    UserRepository.create(db_session, name="User 1", email="user1@example.com")
    UserRepository.create(db_session, name="User 2", email="user2@example.com")
    UserRepository.create(db_session, name="User 3", email="user3@example.com")

    users, total = UserService.get_users(db_session, page=1, page_size=2)

    assert total == 3
    assert [user.name for user in users] == ["User 1", "User 2"]


def test_create_user_rolls_back_on_integrity_error(db_session: Session) -> None:
    UserRepository.create(db_session, name="User 1", email="dup@example.com")

    with pytest.raises(ConflictError) as exc_info:
        UserRepository.create(db_session, name="User 2", email="dup@example.com")

    assert exc_info.value.status_code == 409
    assert db_session.query(User).count() == 1


def test_get_user_returns_user_by_id(db_session: Session) -> None:
    created = UserRepository.create(db_session, name="Lookup User", email="lookup@example.com")

    found = UserService.get_user(db_session, created.id)

    assert found.id == created.id
    assert found.name == created.name


def test_get_user_raises_404_for_missing_user(db_session: Session) -> None:
    with pytest.raises(NotFoundError) as exc_info:
        UserService.get_user(db_session, 999)

    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "User not found"
