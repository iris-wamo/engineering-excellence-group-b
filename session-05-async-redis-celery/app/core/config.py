"""Application settings loaded from the environment."""

from pydantic import MongoDsn, PostgresDsn, RedisDsn, model_validator
from taskflow_shared.config import BaseAppSettings
from taskflow_shared.enums.common import Environment


class Settings(BaseAppSettings):
    """App settings, read from the .env file."""

    database_url: PostgresDsn
    mongo_url: MongoDsn
    mongo_db: str

    # Redis and Celery configuration
    redis_url: RedisDsn = RedisDsn("redis://localhost:6379/0")
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # JWT access tokens. Override jwt_secret_key via the environment in production.
    jwt_secret_key: str = "dev-only-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15

    # Multi-tenancy fallback for unauthenticated requests
    allow_anonymous_default_workspace: bool = True

    @model_validator(mode="after")
    def validate_jwt_secret_key(self) -> "Settings":
        if (
            self.environment not in (Environment.DEVELOPMENT, Environment.TESTING)
            and self.jwt_secret_key == "dev-only-secret-change-in-production"
        ):
            raise ValueError(
                "jwt_secret_key must be configured via environment variable outside dev/test"
            )
        return self


settings = Settings()
