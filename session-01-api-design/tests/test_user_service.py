import pytest
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

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

    with pytest.raises(HTTPException) as exc_info:
        UserService.create_user(db_session, payload)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Email already exists"


def test_get_users_returns_empty_list_when_no_users_exist(db_session: Session) -> None:
    users = UserService.get_users(db_session)

    assert users == []


def test_get_users_supports_limit_and_offset(db_session: Session) -> None:
    UserRepository.create(db_session, name="User 1", email="user1@example.com")
    UserRepository.create(db_session, name="User 2", email="user2@example.com")
    UserRepository.create(db_session, name="User 3", email="user3@example.com")

    users = UserService.get_users(db_session, limit=2, offset=1)

    assert len(users) == 2
    assert [user.name for user in users] == ["User 2", "User 3"]


def test_create_user_rolls_back_on_integrity_error(db_session: Session) -> None:
    UserRepository.create(db_session, name="User 1", email="dup@example.com")

    with pytest.raises(HTTPException) as exc_info:
        UserRepository.create(db_session, name="User 2", email="dup@example.com")

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert db_session.query(User).count() == 1


def test_get_user_returns_user_by_id(db_session: Session) -> None:
    created = UserRepository.create(db_session, name="Lookup User", email="lookup@example.com")

    found = UserService.get_user(db_session, created.id)

    assert found.id == created.id
    assert found.name == created.name


def test_get_user_raises_404_for_missing_user(db_session: Session) -> None:
    with pytest.raises(HTTPException) as exc_info:
        UserService.get_user(db_session, 999)

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "User not found"
