from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration, overridable through environment variables."""

    hospital_api_base_url: str = "https://hospital-directory.onrender.com"
    max_csv_rows: int = Field(default=20, ge=1)
    max_upload_bytes: int = Field(default=1_048_576, ge=1)
    max_concurrency: int = Field(default=20, ge=1)
    request_timeout_seconds: float = Field(default=30.0, gt=0)
    max_retries: int = Field(default=3, ge=1)
    retry_backoff_seconds: float = Field(default=0.5, ge=0)
    max_stored_batches: int = Field(default=500, ge=1)
    # Where the built front end lives (output of `npm run build` in frontend/).
    ui_dir: Path = Path(__file__).resolve().parent / "static"


@lru_cache
def get_settings() -> Settings:
    return Settings()
