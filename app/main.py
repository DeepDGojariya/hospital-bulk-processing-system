import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import bulk, health, progress, ui
from app.api.errors import register_error_handlers
from app.api.limits import MULTIPART_OVERHEAD_BYTES, MaxBodySizeMiddleware
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
    # No effect when logging is already configured, for example under pytest.
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

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
                max_concurrency=settings.max_concurrency,
            )
            store = InMemoryBatchStore(max_batches=settings.max_stored_batches)
            processor = BatchProcessor(client, store)
            app.state.store = store
            app.state.processor = processor
            try:
                yield
            finally:
                # Stop background runs while the HTTP client is still open.
                await processor.shutdown()

    app = FastAPI(
        title="Hospital Bulk Processing API",
        description="Bulk CSV processing on top of the Hospital Directory API.",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    register_error_handlers(app)
    app.add_middleware(
        MaxBodySizeMiddleware, max_bytes=settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES
    )
    app.include_router(health.router)
    app.include_router(bulk.router)
    app.include_router(progress.router)
    app.include_router(ui.router)
    assets = settings.ui_dir / "assets"
    if assets.is_dir():  # absent until the front end has been built
        app.mount("/assets", StaticFiles(directory=assets), name="assets")
    return app


app = create_app()
