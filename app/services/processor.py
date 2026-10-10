"""Orchestrates a bulk run: create rows concurrently, then activate the batch."""

import asyncio
import logging
import time
from uuid import uuid4

from app.clients.hospital_directory import HospitalDirectory, UpstreamError, UpstreamHospital
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
    def __init__(self, client: HospitalDirectory, store: BatchStore) -> None:
        self._client = client
        self._store = store
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
                # The client bounds how many of these are in flight at once.
                async with asyncio.TaskGroup() as group:
                    for state in batch.rows:
                        if state.hospital_id is None:
                            group.create_task(self._create_row(batch, state))
            if all(state.hospital_id is not None for state in batch.rows):
                await self._activate(batch)
        finally:
            # Also reached on cancellation, so a batch is never left processing.
            for state in batch.rows:
                if state.status is RowStatus.PENDING:
                    state.status = RowStatus.FAILED
                    state.error = "Processing was interrupted before this row finished"
            batch.processing_seconds += time.perf_counter() - started
            batch.status = BatchStatus.COMPLETED if batch.activated else BatchStatus.FAILED
            self._store.save(batch)
            result = batch.to_result()
            logger.info(
                "Batch %s %s: %d of %d created, %d failed, %.3fs",
                batch.batch_id,
                batch.status.value,
                result.processed_hospitals,
                result.total_hospitals,
                result.failed_hospitals,
                result.processing_time_seconds,
            )
        return result

    async def prepare_resume(self, batch: BatchState) -> None:
        """Claim a failed batch and sync it with upstream. Follow with `run`."""
        if batch.status is not BatchStatus.FAILED:
            raise BatchNotResumable(f"Batch is {batch.status.value}; only a failed batch resumes")
        # Checked and set without an await in between, so two concurrent
        # resume requests cannot both claim the batch.
        batch.status = BatchStatus.PROCESSING
        try:
            upstream = await self._client.list_batch(batch.batch_id)
        except BaseException as exc:
            # Whatever went wrong (including cancellation), release the claim
            # and tell subscribers, or the batch could never be resumed again.
            batch.status = BatchStatus.FAILED
            self._store.save(batch)
            if isinstance(exc, UpstreamError):
                logger.warning("Batch %s could not be reconciled: %s", batch.batch_id, exc)
                raise ReconciliationError(str(exc)) from exc
            raise

        self._reconcile(batch, upstream)
        batch.activation_error = None
        for state in batch.rows:
            if state.hospital_id is None:
                state.status = RowStatus.PENDING
                state.error = None
        self._store.save(batch)

    def run_in_background(self, batch: BatchState) -> None:
        task = asyncio.create_task(self.run(batch))
        # Hold a reference: the event loop only keeps weak references to tasks.
        self._background_tasks.add(task)
        task.add_done_callback(self._on_background_done)

    async def shutdown(self) -> None:
        """Stop background runs. Their unfinished rows are marked failed."""
        tasks = list(self._background_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _on_background_done(self, task: asyncio.Task[BatchResult]) -> None:
        self._background_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Background batch run failed", exc_info=task.exception())

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
                logger.info(
                    "Batch %s row %d adopted existing upstream hospital %d",
                    batch.batch_id,
                    state.row.row,
                    match.id,
                )

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
            await self._client.ping()
        except UpstreamError as exc:
            logger.warning("Batch %s not started, upstream unavailable: %s", batch.batch_id, exc)
            for state in todo:
                state.status = RowStatus.FAILED
                state.error = f"Hospital directory unavailable: {exc}"
            return False
        return True

    async def _create_row(self, batch: BatchState, state: RowState) -> None:
        try:
            state.hospital_id = await self._client.create_hospital(state.row, batch.batch_id)
        except UpstreamError as exc:
            logger.warning("Batch %s row %d failed: %s", batch.batch_id, state.row.row, exc)
            state.status = RowStatus.FAILED
            state.error = str(exc)
        except Exception as exc:
            # A bug must not take the other rows down or lose the batch: record
            # it on the row so the caller still gets a batch ID to resume.
            logger.exception(
                "Batch %s row %d hit an unexpected error", batch.batch_id, state.row.row
            )
            state.status = RowStatus.FAILED
            state.error = f"Unexpected error: {exc!r}"
        else:
            state.status = RowStatus.CREATED
            state.error = None
        self._store.save(batch)

    async def _activate(self, batch: BatchState) -> None:
        try:
            await self._client.activate_batch(batch.batch_id)
        except UpstreamError as exc:
            logger.warning("Batch %s activation failed: %s", batch.batch_id, exc)
            batch.activation_error = str(exc)
            return
        batch.activated = True
        batch.activation_error = None
        for state in batch.rows:
            state.status = RowStatus.CREATED_AND_ACTIVATED
