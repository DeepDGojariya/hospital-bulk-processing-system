from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration, overridable through environment variables."""

    hospital_api_base_url: str = "https://hospital-directory.onrender.com"
    max_csv_rows: int = 20
    max_upload_bytes: int = 1_048_576
    max_concurrency: int = 20
    request_timeout_seconds: float = 30.0
    max_retries: int = 3
    retry_backoff_seconds: float = 0.5
    max_stored_batches: int = 500


@lru_cache
def get_settings() -> Settings:
    return Settings()
