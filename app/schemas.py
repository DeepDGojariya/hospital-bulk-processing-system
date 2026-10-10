from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel


class BatchStatus(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class RowStatus(StrEnum):
    PENDING = "pending"
    CREATED = "created"
    CREATED_AND_ACTIVATED = "created_and_activated"
    FAILED = "failed"


class HospitalRow(BaseModel):
    """One validated CSV data row. `row` is 1-based and excludes the header."""

    row: int
    name: str
    address: str
    phone: str | None = None


class CsvError(BaseModel):
    row: int | None = None
    field: str | None = None
    message: str


class ValidationReport(BaseModel):
    valid: bool
    total_rows: int
    errors: list[CsvError]


class HospitalResult(BaseModel):
    row: int
    hospital_id: int | None
    name: str
    status: RowStatus
    error: str | None


class BatchResult(BaseModel):
    batch_id: UUID
    status: BatchStatus
    total_hospitals: int
    processed_hospitals: int
    failed_hospitals: int
    processing_time_seconds: float
    batch_activated: bool
    activation_error: str | None
    hospitals: list[HospitalResult]
