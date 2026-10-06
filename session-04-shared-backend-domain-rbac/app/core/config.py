"""Application settings loaded from the environment."""

from pydantic import MongoDsn, PostgresDsn
from taskflow_shared.config import BaseAppSettings


class Settings(BaseAppSettings):
    """App settings, read from the .env file."""

    database_url: PostgresDsn
    mongo_url: MongoDsn
    mongo_db: str


settings = Settings()
