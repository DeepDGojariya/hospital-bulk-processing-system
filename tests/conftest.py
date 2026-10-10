import httpx
import pytest

from app.clients.hospital_directory import HospitalDirectoryClient
from tests.fakes import FakeDirectory


@pytest.fixture
def directory() -> FakeDirectory:
    return FakeDirectory()


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
async def upstream(directory, sleeps):
    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async with httpx.AsyncClient(
        base_url="http://directory.test", transport=httpx.MockTransport(directory)
    ) as http:
        yield HospitalDirectoryClient(http, max_retries=3, backoff_seconds=0.5, sleep=record_sleep)
