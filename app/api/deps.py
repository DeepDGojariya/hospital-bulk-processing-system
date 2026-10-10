from typing import Annotated

from fastapi import Depends
from starlette.requests import HTTPConnection

from app.config import Settings, get_settings
from app.services.processor import BatchProcessor
from app.store.base import BatchStore


def get_store(connection: HTTPConnection) -> BatchStore:
    return connection.app.state.store


def get_processor(connection: HTTPConnection) -> BatchProcessor:
    return connection.app.state.processor


SettingsDep = Annotated[Settings, Depends(get_settings)]
StoreDep = Annotated[BatchStore, Depends(get_store)]
ProcessorDep = Annotated[BatchProcessor, Depends(get_processor)]
