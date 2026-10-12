from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import settings
from app.core.exceptions import NotAuthenticatedError

# bcrypt only reads the first 72 bytes of a password, schemas reject longer ones
MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Return True when the plain-text password matches the stored hash.

    An over-long password is treated as a mismatch rather than an error. bcrypt raises on
    more than MAX_PASSWORD_BYTES, and signup rejects those, so such a password can never
    match a hash we stored. Returning False keeps login's answer a uniform 401 instead of
    a 500 that would reveal which emails have an account.
    """
    password_bytes = password.encode()
    if len(password_bytes) > MAX_PASSWORD_BYTES:
        return False
    return bcrypt.checkpw(password_bytes, password_hash.encode())


def create_access_token(user_id: int) -> str:
    """Create a signed JWT that identifies the user for a limited time."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> int:
    """Validate a JWT and return the user id it was issued for."""
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        return int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise NotAuthenticatedError() from None
