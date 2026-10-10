from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.api import bulk, health, progress
from app.api.errors import register_error_handlers
from app.clients.hospital_directory import HospitalDirectoryClient
from app.config import Settings, get_settings
from app.services.processor import BatchProcessor
from app.store.memory import InMemoryBatchStore


def create_app(
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Build the application. `transport` lets tests replace the upstream API."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # One pooled HTTP client for the life of the process: connections to
        # the upstream are reused across rows and across batches.
        async with httpx.AsyncClient(
            base_url=settings.hospital_api_base_url,
            timeout=settings.request_timeout_seconds,
            limits=httpx.Limits(
                max_connections=settings.max_concurrency,
                max_keepalive_connections=settings.max_concurrency,
            ),
            transport=transport,
        ) as http:
            client = HospitalDirectoryClient(
                http,
                max_retries=settings.max_retries,
                backoff_seconds=settings.retry_backoff_seconds,
            )
            store = InMemoryBatchStore(max_batches=settings.max_stored_batches)
            app.state.store = store
            app.state.processor = BatchProcessor(
                client, store, max_concurrency=settings.max_concurrency
            )
            yield

    app = FastAPI(
        title="Hospital Bulk Processing API",
        description="Bulk CSV processing on top of the Hospital Directory API.",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(bulk.router)
    app.include_router(progress.router)
    return app


app = create_app()
