"""Batch state and the storage interface the rest of the app depends on."""

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.schemas import BatchResult, BatchStatus, HospitalResult, HospitalRow, RowStatus


@dataclass
class RowState:
    row: HospitalRow
    status: RowStatus = RowStatus.PENDING
    hospital_id: int | None = None
    error: str | None = None


@dataclass
class BatchState:
    batch_id: UUID
    rows: list[RowState]
    status: BatchStatus = BatchStatus.PROCESSING
    activated: bool = False
    activation_error: str | None = None
    processing_seconds: float = 0.0

    def to_result(self) -> BatchResult:
        return BatchResult(
            batch_id=self.batch_id,
            status=self.status,
            total_hospitals=len(self.rows),
            processed_hospitals=sum(state.hospital_id is not None for state in self.rows),
            failed_hospitals=sum(state.status is RowStatus.FAILED for state in self.rows),
            processing_time_seconds=round(self.processing_seconds, 3),
            batch_activated=self.activated,
            activation_error=self.activation_error,
            hospitals=[
                HospitalResult(
                    row=state.row.row,
                    hospital_id=state.hospital_id,
                    name=state.row.name,
                    status=state.status,
                    error=state.error,
                )
                for state in self.rows
            ],
        )


class BatchStore(Protocol):
    def save(self, batch: BatchState) -> None:
        """Persist the batch and publish its current snapshot to subscribers."""

    def get(self, batch_id: UUID) -> BatchState | None: ...

    def subscribe(self, batch_id: UUID) -> AsyncGenerator[BatchResult]:
        """Yield the current snapshot, then updates until the batch stops processing."""
