from enum import StrEnum
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, UploadFile, status

from app.api.deps import ProcessorDep, SettingsDep, StoreDep
from app.api.errors import CsvValidationError
from app.config import Settings
from app.schemas import BatchResult, BatchSummary, ValidationReport
from app.services.csv_parser import ParsedCsv, parse_hospital_csv
from app.services.processor import BatchNotResumable, BatchProcessor, ReconciliationError
from app.store.base import BatchState

router = APIRouter(prefix="/hospitals/bulk", tags=["bulk"])


class Mode(StrEnum):
    SYNC = "sync"
    ASYNC = "async"


async def parse_upload(file: UploadFile, settings: Settings) -> ParsedCsv:
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            413,
            f"Upload exceeds the {settings.max_upload_bytes} byte limit",
        )
    return parse_hospital_csv(content, settings.max_csv_rows)


async def execute(
    batch: BatchState,
    mode: Mode,
    processor: BatchProcessor,
    request: Request,
    response: Response,
) -> BatchResult:
    """Run the batch inline, or start it in the background and answer 202."""
    if mode is Mode.SYNC:
        return await processor.run(batch)
    processor.run_in_background(batch)
    response.status_code = status.HTTP_202_ACCEPTED
    response.headers["Location"] = request.app.url_path_for("get_batch", batch_id=batch.batch_id)
    return batch.to_result()


@router.post(
    "",
    response_model=BatchResult,
    summary="Create hospitals from a CSV as one batch",
    responses={
        202: {"model": BatchResult, "description": "Accepted (mode=async)"},
        413: {"description": "Upload too large"},
        422: {"description": "CSV validation failed"},
    },
)
async def bulk_create(
    request: Request,
    response: Response,
    file: UploadFile,
    processor: ProcessorDep,
    settings: SettingsDep,
    mode: Mode = Mode.SYNC,
) -> BatchResult:
    parsed = await parse_upload(file, settings)
    if not parsed.valid:
        raise CsvValidationError(parsed.errors)
    batch = processor.create_batch(parsed.rows)
    return await execute(batch, mode, processor, request, response)


@router.get("", response_model=list[BatchSummary], summary="List processed batches, newest first")
async def list_batches(store: StoreDep) -> list[BatchSummary]:
    return [batch.to_summary() for batch in store.list()]


@router.post(
    "/validate",
    response_model=ValidationReport,
    summary="Validate a CSV without processing it",
    responses={413: {"description": "Upload too large"}},
)
async def validate_csv(file: UploadFile, settings: SettingsDep) -> ValidationReport:
    parsed = await parse_upload(file, settings)
    return ValidationReport(valid=parsed.valid, total_rows=parsed.total_rows, errors=parsed.errors)


@router.get(
    "/{batch_id}",
    response_model=BatchResult,
    name="get_batch",
    summary="Get batch status and progress",
    responses={404: {"description": "Batch not found"}},
)
async def get_batch(batch_id: UUID, store: StoreDep) -> BatchResult:
    batch = store.get(batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Batch not found")
    return batch.to_result()


@router.post(
    "/{batch_id}/resume",
    response_model=BatchResult,
    summary="Retry the failed part of a batch",
    responses={
        202: {"model": BatchResult, "description": "Accepted (mode=async)"},
        404: {"description": "Batch not found"},
        409: {"description": "Batch is processing or already completed"},
        502: {"description": "Could not read the batch from the hospital directory"},
    },
)
async def resume_batch(
    batch_id: UUID,
    request: Request,
    response: Response,
    store: StoreDep,
    processor: ProcessorDep,
    mode: Mode = Mode.SYNC,
) -> BatchResult:
    batch = store.get(batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Batch not found")
    try:
        await processor.prepare_resume(batch)
    except BatchNotResumable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ReconciliationError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Could not reconcile batch with upstream: {exc}"
        ) from exc
    return await execute(batch, mode, processor, request, response)
