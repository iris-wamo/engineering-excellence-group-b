"""Helpers for building access tokens and request headers in tests.

Tokens are signed with the app's own settings, so they are accepted exactly like
tokens issued by POST /api/v1/auth/login, without the signup/login round trip.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

import jwt
from taskflow_shared.contracts.constants import HEADER_WORKSPACE_ID

from app.auth.security import create_access_token
from app.core.config import settings

DEFAULT_PASSWORD = "sup3r-secret"

# The user the `auth_headers` fixture signs up and logs in as.
AUTH_USER = {"name": "Auth User", "email": "auth-user@example.com", "password": DEFAULT_PASSWORD}


class AuthedUser(NamedTuple):
    """A user plus the headers needed to act as them"""

    id: int
    headers: dict[str, str]


# Type of the `make_user` fixture: make_user(email, role=None, *, project_id=None).
MakeUser = Callable[..., Awaitable[AuthedUser]]


def token_for(user_id: int) -> str:
    """A valid access token for the user, identical to one issued at login."""
    return create_access_token(user_id)


def expired_token_for(user_id: int) -> str:
    """A correctly signed token whose expiry is already in the past."""
    past = datetime.now(UTC) - timedelta(hours=1)
    payload = {"sub": str(user_id), "iat": past - timedelta(minutes=15), "exp": past}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def forged_token_for(user_id: int) -> str:
    """A token for the user signed with the wrong key, as an attacker would produce."""
    payload = {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=15)}
    # 32+ bytes so PyJWT does not warn about a short HMAC key
    wrong_key = "attacker-key-that-is-not-the-real-one"
    return jwt.encode(payload, wrong_key, algorithm=settings.jwt_algorithm)


def bearer(token: str, *, workspace_id: int | None = None) -> dict[str, str]:
    """Authorization header for a token, plus X-Workspace-ID when a workspace is given."""
    headers = {"Authorization": f"Bearer {token}"}
    if workspace_id is not None:
        headers[HEADER_WORKSPACE_ID] = str(workspace_id)
    return headers


def auth_headers_for(user_id: int, *, workspace_id: int | None = None) -> dict[str, str]:
    """Headers that authenticate as the user, optionally inside a specific workspace."""
    return bearer(token_for(user_id), workspace_id=workspace_id)
