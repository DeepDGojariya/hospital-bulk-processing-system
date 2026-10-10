"""Orchestrates a bulk run: create rows concurrently, then activate the batch."""

import asyncio
import logging
import time
from uuid import uuid4

from app.clients.hospital_directory import (
    HospitalDirectoryClient,
    UpstreamError,
    UpstreamHospital,
)
from app.schemas import BatchResult, BatchStatus, HospitalRow, RowStatus
from app.store.base import BatchState, BatchStore, RowState

logger = logging.getLogger(__name__)


class BatchNotResumable(Exception):
    """Only a failed batch can be resumed."""


class ReconciliationError(Exception):
    """The upstream batch could not be read, so resuming is not safe."""


def _identity(name: str, address: str, phone: str | None) -> tuple[str, str, str | None]:
    """Fields that identify a hospital, tolerant of padding and blank-vs-null phone."""
    return name.strip(), address.strip(), (phone or "").strip() or None


class BatchProcessor:
    def __init__(
        self, client: HospitalDirectoryClient, store: BatchStore, *, max_concurrency: int
    ) -> None:
        self._client = client
        self._store = store
        # One semaphore for the whole service, so concurrent uploads cannot
        # multiply the load placed on the upstream API.
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._background_tasks: set[asyncio.Task[BatchResult]] = set()

    def create_batch(self, rows: list[HospitalRow]) -> BatchState:
        batch = BatchState(batch_id=uuid4(), rows=[RowState(row=row) for row in rows])
        self._store.save(batch)
        return batch

    async def run(self, batch: BatchState) -> BatchResult:
        """Create every row that has no hospital yet, then activate the batch."""
        started = time.perf_counter()
        try:
            if await self._upstream_ready(batch):
                async with asyncio.TaskGroup() as group:
                    for state in batch.rows:
                        if state.hospital_id is None:
                            group.create_task(self._create_row(batch, state))
            if all(state.hospital_id is not None for state in batch.rows):
                await self._activate(batch)
        finally:
            batch.processing_seconds += time.perf_counter() - started
            batch.status = BatchStatus.COMPLETED if batch.activated else BatchStatus.FAILED
            self._store.save(batch)
        return batch.to_result()

    async def prepare_resume(self, batch: BatchState) -> None:
        """Claim a failed batch and sync it with upstream. Follow with `run`."""
        if batch.status is not BatchStatus.FAILED:
            raise BatchNotResumable(f"Batch is {batch.status.value}; only a failed batch resumes")
        # Checked and set without an await in between, so two concurrent
        # resume requests cannot both claim the batch.
        batch.status = BatchStatus.PROCESSING
        try:
            async with self._semaphore:
                upstream = await self._client.list_batch(batch.batch_id)
        except BaseException as exc:
            # Whatever went wrong (including cancellation), release the claim
            # and tell subscribers, or the batch could never be resumed again.
            batch.status = BatchStatus.FAILED
            self._store.save(batch)
            if isinstance(exc, UpstreamError):
                raise ReconciliationError(str(exc)) from exc
            raise

        self._reconcile(batch, upstream)
        batch.activation_error = None
        for state in batch.rows:
            if state.hospital_id is None:
                state.status = RowStatus.PENDING
                state.error = None
        self._store.save(batch)

    @staticmethod
    def _reconcile(batch: BatchState, upstream: list[UpstreamHospital]) -> None:
        """Adopt hospitals that exist upstream but that we recorded as failed.

        This happens when a create request timed out after the upstream had
        already stored the hospital.
        """
        known_ids = {state.hospital_id for state in batch.rows if state.hospital_id is not None}
        orphans = [hospital for hospital in upstream if hospital.id not in known_ids]
        for state in batch.rows:
            if state.hospital_id is not None:
                continue
            match = next(
                (
                    hospital
                    for hospital in orphans
                    if _identity(hospital.name, hospital.address, hospital.phone)
                    == _identity(state.row.name, state.row.address, state.row.phone)
                ),
                None,
            )
            if match is not None:
                orphans.remove(match)
                state.hospital_id = match.id
                state.status = RowStatus.CREATED
                state.error = None

    def run_in_background(self, batch: BatchState) -> None:
        task = asyncio.create_task(self.run(batch))
        # Hold a reference: the event loop only keeps weak references to tasks.
        self._background_tasks.add(task)
        task.add_done_callback(self._on_background_done)

    def _on_background_done(self, task: asyncio.Task[BatchResult]) -> None:
        self._background_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Background batch run failed", exc_info=task.exception())

    async def _upstream_ready(self, batch: BatchState) -> bool:
        """Wake the upstream before sending creates; fail the rows if it stays down.

        The upstream can take longer than our timeout to cold-start. A create
        that times out cannot be retried safely, so the first request is a
        harmless one that can be.
        """
        todo = [state for state in batch.rows if state.hospital_id is None]
        if not todo:
            return True
        try:
            async with self._semaphore:
                await self._client.ping()
        except UpstreamError as exc:
            for state in todo:
                state.status = RowStatus.FAILED
                state.error = f"Hospital directory unavailable: {exc}"
            return False
        return True

    async def _create_row(self, batch: BatchState, state: RowState) -> None:
        async with self._semaphore:
            try:
                state.hospital_id = await self._client.create_hospital(state.row, batch.batch_id)
            except UpstreamError as exc:
                state.status = RowStatus.FAILED
                state.error = str(exc)
            else:
                state.status = RowStatus.CREATED
                state.error = None
        self._store.save(batch)

    async def _activate(self, batch: BatchState) -> None:
        try:
            async with self._semaphore:
                await self._client.activate_batch(batch.batch_id)
        except UpstreamError as exc:
            batch.activation_error = str(exc)
            return
        batch.activated = True
        batch.activation_error = None
        for state in batch.rows:
            state.status = RowStatus.CREATED_AND_ACTIVATED
