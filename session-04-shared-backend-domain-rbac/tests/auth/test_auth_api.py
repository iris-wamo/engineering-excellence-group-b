from datetime import UTC, datetime, timedelta

import jwt
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User
from tests.conftest import AUTH_USER

SIGNUP = {"name": "New User", "email": "new-user@example.com", "password": "sup3r-secret"}


async def test_signup_returns_201_without_password_fields(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/signup", json=SIGNUP)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "New User"
    assert body["email"] == "new-user@example.com"
    assert body["is_active"] is True
    assert "password" not in body
    assert "password_hash" not in body


async def test_signup_returns_conflict_for_duplicate_email(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/signup", json=SIGNUP)

    response = await client.post("/api/v1/auth/signup", json=SIGNUP)

    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "CONFLICT"
    assert body["error"]["message"] == "Email already exists"


async def test_signup_stores_a_hash_not_the_plain_password(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await client.post("/api/v1/auth/signup", json=SIGNUP)

    user = (await db_session.scalars(select(User).where(User.email == SIGNUP["email"]))).one()

    assert user.password_hash is not None
    assert user.password_hash != SIGNUP["password"]
    assert SIGNUP["password"] not in user.password_hash
    assert user.password_hash.startswith("$2b$")


async def test_login_returns_access_token(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/signup", json=SIGNUP)

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": SIGNUP["email"], "password": SIGNUP["password"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert "password" not in body
    assert "password_hash" not in body


async def test_login_returns_401_for_wrong_password(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/signup", json=SIGNUP)

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": SIGNUP["email"], "password": "wrong-password"},
    )

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "UNAUTHENTICATED"
    assert body["error"]["message"] == "Invalid email or password"


async def test_login_returns_401_for_unknown_user(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "sup3r-secret"},
    )

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "UNAUTHENTICATED"
    assert body["error"]["message"] == "Invalid email or password"


async def test_me_identifies_the_logged_in_user(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/auth/me", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == AUTH_USER["email"]
    assert "password" not in body
    assert "password_hash" not in body


async def test_protected_endpoint_rejects_missing_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "UNAUTHENTICATED"
    assert body["error"]["message"] == "Missing or invalid authentication credentials"


async def test_protected_endpoint_rejects_invalid_token(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "UNAUTHENTICATED"
    assert body["error"]["message"] == "Missing or invalid authentication credentials"


async def test_protected_endpoint_rejects_expired_token(client: AsyncClient) -> None:
    expired_token = jwt.encode(
        {"sub": "1", "exp": datetime.now(UTC) - timedelta(minutes=1)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_signup_rejects_multibyte_password_over_byte_limit(client: AsyncClient) -> None:
    # 40 characters, but 80 bytes once UTF-8 encoded: under a character limit, over bcrypt's.
    long_password = "é" * 40
    assert len(long_password) == 40
    assert len(long_password.encode()) == 80

    response = await client.post(
        "/api/v1/auth/signup",
        json={"name": "Multibyte", "email": "multibyte@example.com", "password": long_password},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_login_with_password_over_byte_limit_returns_401(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/signup", json=SIGNUP)

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": SIGNUP["email"], "password": "a" * 100},
    )

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "UNAUTHENTICATED"
    assert body["error"]["message"] == "Invalid email or password"


async def test_login_as_inactive_user_returns_401(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await client.post("/api/v1/auth/signup", json=SIGNUP)
    user = (await db_session.scalars(select(User).where(User.email == SIGNUP["email"]))).one()
    user.is_active = False
    await db_session.commit()

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": SIGNUP["email"], "password": SIGNUP["password"]},
    )

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "UNAUTHENTICATED"
    assert body["error"]["message"] == "Invalid email or password"
