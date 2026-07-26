from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.schemas.user import UserCreate
from app.services.user_service import UserService


def test_create_user_returns_201_and_payload(client: TestClient) -> None:
    response = client.post(
        "/users",
        json={"name": "User", "email": "user@example.com"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "User"
    assert body["email"] == "user@example.com"
    assert body["is_active"] is True


def test_create_user_rejects_invalid_email(client: TestClient) -> None:
    response = client.post(
        "/users",
        json={"name": "User", "email": "not-an-email"},
    )

    assert response.status_code == 422


def test_get_users_returns_empty_list(client: TestClient) -> None:
    response = client.get("/users")

    assert response.status_code == 200
    assert response.json() == []


def test_get_user_returns_404_for_missing_user(client: TestClient) -> None:
    response = client.get("/users/99900000")

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


def test_get_users_supports_pagination(client: TestClient, db_session: Session) -> None:
    UserService.create_user(db_session, UserCreate(name="User 1", email="user1@example.com"))
    UserService.create_user(db_session, UserCreate(name="User 2", email="user2@example.com"))
    UserService.create_user(db_session, UserCreate(name="User 3", email="user3@example.com"))

    response = client.get("/users?limit=2&offset=1")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert [item["name"] for item in body] == ["User 2", "User 3"]
