from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.schemas import CsvError


class CsvValidationError(Exception):
    def __init__(self, errors: list[CsvError]) -> None:
        super().__init__("CSV validation failed")
        self.errors = errors


async def _csv_validation_handler(request: Request, exc: CsvValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": "CSV validation failed",
            "errors": [error.model_dump() for error in exc.errors],
        },
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(CsvValidationError, _csv_validation_handler)
