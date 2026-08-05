from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.user import UserCreate
from app.services.user_service import UserService


async def test_create_user_returns_201_and_payload(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/users",
        json={"name": "User", "email": "user@example.com"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "User"
    assert body["email"] == "user@example.com"
    assert body["is_active"] is True
    assert response.headers.get("location") == f"/api/v1/users/{body['id']}"


async def test_create_user_rejects_invalid_email(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/users",
        json={"name": "User", "email": "not-an-email"},
    )

    assert response.status_code == 422


async def test_create_user_returns_conflict_for_duplicate_email(client: AsyncClient) -> None:
    await client.post("/api/v1/users", json={"name": "User", "email": "duplicate@example.com"})

    response = await client.post(
        "/api/v1/users", json={"name": "User", "email": "duplicate@example.com"}
    )

    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "CONFLICT"
    assert body["error"]["message"] == "Email already exists"


async def test_get_user_returns_created_user_by_id(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/users", json={"name": "User", "email": "lookup@example.com"}
    )
    created = response.json()

    response = await client.get(f"/api/v1/users/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]
    assert response.json()["email"] == "lookup@example.com"


async def test_get_users_returns_empty_list(client: AsyncClient) -> None:
    response = await client.get("/api/v1/users")

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["page"] == 1
    assert body["page_size"] == 10


async def test_get_user_returns_404_for_missing_user(client: AsyncClient) -> None:
    response = await client.get("/api/v1/users/99900000")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["message"] == "User not found"


async def test_get_users_supports_pagination(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await UserService.create_user(db_session, UserCreate(name="User 1", email="user1@example.com"))
    await UserService.create_user(db_session, UserCreate(name="User 2", email="user2@example.com"))
    await UserService.create_user(db_session, UserCreate(name="User 3", email="user3@example.com"))

    response = await client.get("/api/v1/users?page=1&page_size=2")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert [item["name"] for item in body["items"]] == ["User 1", "User 2"]
