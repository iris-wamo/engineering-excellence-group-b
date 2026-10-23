"""Application settings loaded from the environment."""

from pydantic import MongoDsn, PostgresDsn, RedisDsn, model_validator
from taskflow_shared.config import BaseAppSettings
from taskflow_shared.enums.common import Environment


class Settings(BaseAppSettings):
    """App settings, read from the .env file."""

    database_url: PostgresDsn
    mongo_url: MongoDsn
    mongo_db: str

    # Redis: task events are published to a Pub/Sub channel and a Stream side by side
    # (see docs/session-05/redis-pubsub-vs-streams.md).
    redis_url: RedisDsn = RedisDsn("redis://localhost:6379/0")
    task_events_channel: str = "taskflow:task-events"
    task_events_stream: str = "taskflow:task-events:stream"
    task_events_stream_group: str = "task-event-processors"
    task_events_stream_maxlen: int = 10_000
    task_events_dead_letter_stream: str = "taskflow:task-events:dead-letter"
    # Task summary cache: how long cached metrics may be served at most (see
    # docs/session-05/redis-caching.md). Writes invalidate earlier; this is the safety net.
    task_summary_cache_ttl_seconds: int = 30
    # Celery broker and result backend (separate Redis databases from REDIS_URL)
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    # Outbox sweep: re-publish assignment notifications left 'pending' longer than this
    notification_requeue_after_minutes: int = 5
    notification_requeue_interval_seconds: float = 300.0
    notification_requeue_batch_size: int = 100
    # After this many re-publishes without delivery the row is marked 'failed'
    notification_requeue_max_attempts: int = 10
    # Due-task reminders (Celery Beat): remind assignees of tasks due within the window
    due_reminder_window_days: int = 1
    due_reminder_interval_seconds: float = 60.0
    # At most one reminder per task, assignee and due date within this many hours. It is
    # how often a person may be reminded, so it does not follow the sweep interval.
    due_reminder_dedup_hours: int = 24
    due_reminder_batch_size: int = 500
    # Flower port, used by `make flower` and the Compose `flower` service
    flower_port: int = 5555

    @property
    def due_reminder_lock_ttl_seconds(self) -> int:
        """Expiry of the sweep's Redis lock: five sweep intervals, at least a minute.

        The running sweep keeps renewing it, so the TTL only bounds how long a crashed
        sweep blocks the next ones.
        """
        return max(60, int(self.due_reminder_interval_seconds * 5))

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
