from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import decode_access_token
from app.core.exceptions import NotAuthenticatedError
from app.db.session import get_db
from app.models.user import User
from app.repositories.user_repository import UserRepository

# auto_error=False so a missing header raises our own AuthenticationError
# instead of FastAPI's default error shape.
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    """Read the Bearer token, validate it, and load the user it belongs to"""
    if credentials is None:
        raise NotAuthenticatedError()

    user_id = decode_access_token(credentials.credentials)

    user = await UserRepository.get_by_id(db, user_id)
    if user is None or not user.is_active:
        raise NotAuthenticatedError()

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
