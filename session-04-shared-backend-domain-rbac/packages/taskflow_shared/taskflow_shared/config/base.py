"""Base configuration settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict

from taskflow_shared.enums.common import Environment


class BaseAppSettings(BaseSettings):
    """Common application configuration settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = Environment.DEVELOPMENT
    app_name: str = "taskflow"
    debug: bool = False
