from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import create_access_token, hash_password, verify_password
from app.core.exceptions import InvalidCredentialsError
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_user import WorkspaceUser
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, SignupRequest


class AuthService:
    @staticmethod
    async def signup(db: AsyncSession, payload: SignupRequest) -> User:
        """Register a new user, storing only the hash of their password."""
        user = await UserRepository.create(
            db,
            name=payload.name,
            email=str(payload.email),
            password_hash=hash_password(payload.password),
        )
        # Automatically enroll user into default workspace 1 if it exists
        ws = await db.get(Workspace, 1)
        if ws is not None:
            db.add(WorkspaceUser(workspace_id=1, user_id=user.id))
            await db.commit()
            await db.refresh(user)

        return user

    @staticmethod
    async def login(db: AsyncSession, payload: LoginRequest) -> str:
        """Verify credentials and return a signed access token."""
        user = await UserRepository.get_by_email(db, str(payload.email))

        # An unknown email, an account with no password, and a deactivated account all
        # raise the same error
        if user is None or user.password_hash is None or not user.is_active:
            raise InvalidCredentialsError()

        if not verify_password(payload.password, user.password_hash):
            raise InvalidCredentialsError()

        return create_access_token(user.id)
