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
    # Outbox sweep: re-publish assignment notifications left 'pending' longer than this
    notification_requeue_after_minutes: int = 5
    notification_requeue_interval_seconds: float = 300.0
    notification_requeue_batch_size: int = 100
    # After this many re-publishes without delivery the row is marked 'failed'
    notification_requeue_max_attempts: int = 10
    due_reminder_window_days: int = 1
    celery_beat_schedule_interval_seconds: float = 60.0
    flower_port: int = 5555

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
