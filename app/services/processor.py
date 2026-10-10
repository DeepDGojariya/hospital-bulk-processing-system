"""Orchestrates a bulk run: create rows concurrently, then activate the batch."""

import asyncio
import logging
import time
from uuid import uuid4

from app.clients.hospital_directory import HospitalDirectoryClient, UpstreamError
from app.schemas import BatchResult, BatchStatus, HospitalRow, RowStatus
from app.store.base import BatchState, BatchStore, RowState

logger = logging.getLogger(__name__)


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

    def run_in_background(self, batch: BatchState) -> None:
        task = asyncio.create_task(self.run(batch))
        # Hold a reference: the event loop only keeps weak references to tasks.
        self._background_tasks.add(task)
        task.add_done_callback(self._on_background_done)

    def _on_background_done(self, task: asyncio.Task[BatchResult]) -> None:
        self._background_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Background batch run failed", exc_info=task.exception())

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
