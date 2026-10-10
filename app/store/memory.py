"""Single-process batch store. State is lost on restart and is not shared across workers."""

import asyncio
from collections import defaultdict
from collections.abc import AsyncGenerator
from uuid import UUID

from app.schemas import BatchResult, BatchStatus
from app.store.base import BatchState


class InMemoryBatchStore:
    def __init__(self, max_batches: int) -> None:
        self._max_batches = max_batches
        self._batches: dict[UUID, BatchState] = {}
        self._subscribers: defaultdict[UUID, set[asyncio.Queue[BatchResult]]] = defaultdict(set)

    def save(self, batch: BatchState) -> None:
        if batch.batch_id not in self._batches:
            self._evict()
            self._batches[batch.batch_id] = batch
        snapshot = batch.to_result()
        for queue in self._subscribers.get(batch.batch_id, ()):
            queue.put_nowait(snapshot)

    def get(self, batch_id: UUID) -> BatchState | None:
        return self._batches.get(batch_id)

    async def subscribe(self, batch_id: UUID) -> AsyncGenerator[BatchResult]:
        batch = self._batches.get(batch_id)
        if batch is None:
            return
        queue: asyncio.Queue[BatchResult] = asyncio.Queue()
        self._subscribers[batch_id].add(queue)
        try:
            snapshot = batch.to_result()
            yield snapshot
            while snapshot.status is BatchStatus.PROCESSING:
                snapshot = await queue.get()
                yield snapshot
        finally:
            self._subscribers[batch_id].discard(queue)
            if not self._subscribers[batch_id]:
                del self._subscribers[batch_id]

    def _evict(self) -> None:
        """Make room for one more batch.

        Completed batches go first, oldest first. Failed batches can still be
        resumed, so they are only dropped when nothing completed is left. A
        batch that is processing is never dropped.
        """
        while len(self._batches) >= self._max_batches:
            victim = self._oldest(BatchStatus.COMPLETED) or self._oldest(BatchStatus.FAILED)
            if victim is None:
                return
            del self._batches[victim]

    def _oldest(self, status: BatchStatus) -> UUID | None:
        return next(
            (batch_id for batch_id, batch in self._batches.items() if batch.status is status),
            None,
        )
