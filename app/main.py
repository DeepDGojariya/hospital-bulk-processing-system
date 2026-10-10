import httpx
from fastapi import FastAPI

from app.api import health
from app.config import Settings, get_settings


def create_app(
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="Hospital Bulk Processing API",
        description="Bulk CSV processing on top of the Hospital Directory API.",
        version="1.0.0",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.include_router(health.router)
    return app


app = create_app()
