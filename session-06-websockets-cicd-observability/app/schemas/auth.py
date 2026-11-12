from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.auth.security import MAX_PASSWORD_BYTES


def validate_password_bytes(value: str) -> str:
    """Reject passwords bcrypt cannot hash.

    Field(max_length=...) counts characters, not bytes, so a short multi-byte password
    such as 40 x "e-acute" (80 bytes) would pass that check and then make bcrypt raise.
    """
    if len(value.encode()) > MAX_PASSWORD_BYTES:
        raise ValueError(
            f"Password must not exceed {MAX_PASSWORD_BYTES} bytes. "
            "Please use a shorter password or fewer special characters."
        )
    return value


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
        description=(
            f"Plain-text password, hashed before storage and never returned. "
            f"At most {MAX_PASSWORD_BYTES} bytes once UTF-8 encoded."
        ),
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

    @field_validator("password")
    @classmethod
    def check_password_bytes(cls, value: str) -> str:
        return validate_password_bytes(value)


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
