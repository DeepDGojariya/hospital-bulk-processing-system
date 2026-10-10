"""Error responses. Every 422 has the same shape: a summary plus a list of errors."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas import CsvError


class CsvValidationError(Exception):
    def __init__(self, errors: list[CsvError]) -> None:
        super().__init__("CSV validation failed")
        self.errors = errors


def _unprocessable(detail: str, errors: list[CsvError]) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": detail, "errors": [error.model_dump() for error in errors]},
    )


async def _csv_validation_handler(request: Request, exc: CsvValidationError) -> JSONResponse:
    return _unprocessable("CSV validation failed", exc.errors)


async def _request_validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = [
        CsvError(field=str(error["loc"][-1]) if error.get("loc") else None, message=error["msg"])
        for error in exc.errors()
    ]
    return _unprocessable("Request validation failed", errors)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(CsvValidationError, _csv_validation_handler)
    app.add_exception_handler(RequestValidationError, _request_validation_handler)
