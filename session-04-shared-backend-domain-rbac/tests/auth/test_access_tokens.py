"""Access token checks: which tokens the API accepts, and the uniform 401 for the rest."""

from collections.abc import Callable

import pytest
from httpx import AsyncClient

from tests.fixtures.auth import (
    DEFAULT_PASSWORD,
    auth_headers_for,
    bearer,
    expired_token_for,
    forged_token_for,
)
from tests.fixtures.factories import MISSING_ID, DataFactory


async def test_minted_token_is_accepted(client: AsyncClient, factory: DataFactory) -> None:
    user = await factory.user(email="minted@example.com")

    response = await client.get("/api/v1/auth/me", headers=auth_headers_for(user.id))

    assert response.status_code == 200
    assert response.json()["email"] == "minted@example.com"


async def test_login_token_matches_minted_token_behavior(
    client: AsyncClient, factory: DataFactory
) -> None:
    """Tokens minted by the helpers must behave like real login tokens, or tests lie."""
    user = await factory.user(email="login@example.com", password=DEFAULT_PASSWORD)
    login = await client.post(
        "/api/v1/auth/login", json={"email": "login@example.com", "password": DEFAULT_PASSWORD}
    )
    token = login.json()["access_token"]

    me = await client.get("/api/v1/auth/me", headers=bearer(token))

    assert me.status_code == 200
    assert me.json()["id"] == user.id


@pytest.mark.parametrize(
    "make_header",
    [
        lambda user_id: bearer(expired_token_for(user_id)),
        lambda user_id: bearer(forged_token_for(user_id)),
        lambda user_id: bearer("not-a-jwt"),
        lambda user_id: {"Authorization": "Basic dXNlcjpwYXNz"},
        lambda user_id: {},
    ],
    ids=["expired", "forged-signature", "garbage", "wrong-scheme", "missing"],
)
async def test_bad_credentials_get_401(
    client: AsyncClient,
    factory: DataFactory,
    make_header: Callable[[int], dict[str, str]],
) -> None:
    user = await factory.user()
    headers = make_header(user.id)

    response = await client.get("/api/v1/auth/me", headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_token_for_deactivated_user_is_rejected(
    client: AsyncClient, factory: DataFactory
) -> None:
    user = await factory.user(is_active=False)

    response = await client.get("/api/v1/auth/me", headers=auth_headers_for(user.id))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_token_for_unknown_user_is_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me", headers=auth_headers_for(MISSING_ID))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_user_without_password_cannot_log_in(
    client: AsyncClient, factory: DataFactory
) -> None:
    """Accounts created before authentication existed have no password hash."""
    await factory.user(email="legacy@example.com")

    response = await client.post(
        "/api/v1/auth/login", json={"email": "legacy@example.com", "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
