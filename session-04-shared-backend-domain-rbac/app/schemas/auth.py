from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.auth.security import MAX_PASSWORD_BYTES


class SignupRequest(BaseModel):
    """Schema for registering a new account."""

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
    password: str = Field(
        ...,
        min_length=8,
        max_length=MAX_PASSWORD_BYTES,
        description="Plain-text password, hashed before storage and never returned.",
        examples=["sup3r-secret"],
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


class LoginRequest(BaseModel):
    """Schema for exchanging credentials for an access token."""

    email: EmailStr = Field(..., description="User email address.", examples=["user@gmail.com"])
    password: str = Field(..., description="Plain-text password.", examples=["sup3r-secret"])

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class TokenResponse(BaseModel):
    """Schema for a successful login response."""

    access_token: str = Field(description="Signed JWT to send as a Bearer token.")
    token_type: str = Field(default="bearer", description="How to use the token.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"access_token": "eyJhbGciOiJIUzI1NiIs...", "token_type": "bearer"}]
        }
    )
