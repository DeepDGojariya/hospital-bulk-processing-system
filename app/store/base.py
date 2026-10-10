"""Batch state and the storage interface the rest of the app depends on."""

from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.schemas import (
    BatchResult,
    BatchStatus,
    BatchSummary,
    HospitalResult,
    HospitalRow,
    RowStatus,
)


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
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def processed_count(self) -> int:
        return sum(state.hospital_id is not None for state in self.rows)

    @property
    def failed_count(self) -> int:
        return sum(state.status is RowStatus.FAILED for state in self.rows)

    def to_summary(self) -> BatchSummary:
        return BatchSummary(
            batch_id=self.batch_id,
            status=self.status,
            created_at=self.created_at,
            total_hospitals=len(self.rows),
            processed_hospitals=self.processed_count,
            failed_hospitals=self.failed_count,
            processing_time_seconds=round(self.processing_seconds, 3),
            batch_activated=self.activated,
        )

    def to_result(self) -> BatchResult:
        return BatchResult(
            batch_id=self.batch_id,
            status=self.status,
            total_hospitals=len(self.rows),
            processed_hospitals=self.processed_count,
            failed_hospitals=self.failed_count,
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

    def list(self) -> list[BatchState]:
        """Every stored batch, newest first."""

    def subscribe(self, batch_id: UUID) -> AsyncGenerator[BatchResult]:
        """Yield the current snapshot, then updates until the batch stops processing."""
