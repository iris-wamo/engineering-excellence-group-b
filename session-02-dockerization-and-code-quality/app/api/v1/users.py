from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.user import UserCreate, UserListResponse, UserResponse
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    response: Response,
) -> UserResponse:
    """Create a new user."""
    user = await UserService.create_user(db, payload)

    response.headers["location"] = f"/api/v1/users/{user.id}"
    return UserResponse.model_validate(user)


@router.get("", response_model=UserListResponse)
async def get_users(
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
) -> UserListResponse:
    """List users, paginated."""
    users, total = await UserService.get_users(db, page=page, page_size=page_size)
    return UserListResponse(
        items=[UserResponse.model_validate(user) for user in users],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: int, db: Annotated[AsyncSession, Depends(get_db)]) -> UserResponse:
    """Retrieve a user by ID."""
    user = await UserService.get_user(db, user_id)
    return UserResponse.model_validate(user)
