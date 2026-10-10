import httpx
import pytest
from fastapi.testclient import TestClient

from app.clients.hospital_directory import HospitalDirectoryClient
from app.config import Settings
from app.main import create_app
from app.services.processor import BatchProcessor
from app.store.memory import InMemoryBatchStore
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
        yield HospitalDirectoryClient(
            http, max_retries=3, backoff_seconds=0.5, max_concurrency=3, sleep=record_sleep
        )


@pytest.fixture
def store() -> InMemoryBatchStore:
    return InMemoryBatchStore(max_batches=50)


@pytest.fixture
def processor(upstream, store) -> BatchProcessor:
    return BatchProcessor(upstream, store)


@pytest.fixture
def client(directory):
    settings = Settings(
        hospital_api_base_url="http://directory.test",
        retry_backoff_seconds=0,
        max_upload_bytes=2048,
    )
    app = create_app(settings, transport=httpx.MockTransport(directory))
    with TestClient(app) as test_client:
        yield test_client
