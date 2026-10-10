import pytest
from pydantic import ValidationError

from app.config import Settings


@pytest.mark.parametrize(
    "field",
    [
        "max_csv_rows",
        "max_upload_bytes",
        "max_concurrency",
        "request_timeout_seconds",
        "max_retries",
        "max_stored_batches",
    ],
)
def test_settings_reject_zero(field):
    with pytest.raises(ValidationError):
        Settings(**{field: 0})


def test_settings_reject_negative_backoff():
    with pytest.raises(ValidationError):
        Settings(retry_backoff_seconds=-1)


def test_zero_backoff_is_allowed():
    assert Settings(retry_backoff_seconds=0).retry_backoff_seconds == 0
