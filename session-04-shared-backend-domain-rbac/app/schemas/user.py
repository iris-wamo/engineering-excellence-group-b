"""Pydantic schemas for user request and response models."""

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    """Schema for creating a new user."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="User's full name.",
        examples=["User Name"],
    )
    email: EmailStr = Field(
        ...,
        description="User email address.",
        examples=["user@gmail.com"],
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned_value = value.strip()

        if not cleaned_value:
            raise ValueError("Name cannot be empty or whitespace only.")

        return cleaned_value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class UserResponse(BaseModel):
    """Schema for returning user details."""

    id: int = Field(description="Unique user identifier.")
    name: str = Field(description="User's full name.")
    email: EmailStr = Field(description="User email address.")
    is_active: bool = Field(description="Whether the user account is active.")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": 1,
                    "name": "User Name",
                    "email": "user@gmail.com",
                    "is_active": True,
                }
            ]
        },
    )


class UserListResponse(BaseModel):
    """Schema for a paginated user list response."""

    items: list[UserResponse] = Field(description="The users on this page")
    total: int = Field(description="Total number of users matching the query")
    page: int = Field(description="Current page number (1-indexed)")
    page_size: int = Field(description="Maximum number of users per page")
