import pytest
from pydantic import ValidationError

from app.schemas.user import UserCreate


def test_user_create_strips_and_validates_name_whitespace() -> None:
    user = UserCreate(name="  User Name  ", email="user@gmail.com")

    assert user.name == "User Name"


def test_user_create_rejects_blank_name_after_stripping() -> None:
    with pytest.raises(ValidationError):
        UserCreate(name="   ", email="user@gmail.com")


def test_user_create_rejects_name_longer_than_database_limit() -> None:
    with pytest.raises(ValidationError):
        UserCreate(name="x" * 101, email="user@gmail.com")
