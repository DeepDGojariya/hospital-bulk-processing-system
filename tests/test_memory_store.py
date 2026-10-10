import asyncio
from uuid import uuid4

from app.schemas import BatchStatus, RowStatus
from app.store.base import BatchState, RowState
from app.store.memory import InMemoryBatchStore
from tests.fakes import make_rows


def make_batch(count: int = 2, status: BatchStatus = BatchStatus.PROCESSING) -> BatchState:
    return BatchState(
        batch_id=uuid4(), rows=[RowState(row=row) for row in make_rows(count)], status=status
    )


def test_to_result_counts_created_failed_and_pending_rows():
    batch = make_batch(3)
    batch.rows[0].status = RowStatus.CREATED
    batch.rows[0].hospital_id = 7
    batch.rows[1].status = RowStatus.FAILED
    batch.rows[1].error = "boom"
    batch.processing_seconds = 1.23456

    result = batch.to_result()

    assert result.total_hospitals == 3
    assert result.processed_hospitals == 1
    assert result.failed_hospitals == 1
    assert result.processing_time_seconds == 1.235
    assert result.batch_activated is False
    assert [(h.row, h.hospital_id, h.name, h.status, h.error) for h in result.hospitals] == [
        (1, 7, "H1", RowStatus.CREATED, None),
        (2, None, "H2", RowStatus.FAILED, "boom"),
        (3, None, "H3", RowStatus.PENDING, None),
    ]


def test_save_and_get():
    store = InMemoryBatchStore(max_batches=10)
    batch = make_batch()

    store.save(batch)

    assert store.get(batch.batch_id) is batch
    assert store.get(uuid4()) is None


def test_evicts_oldest_finished_batch_but_never_a_processing_one():
    store = InMemoryBatchStore(max_batches=2)
    running = make_batch(status=BatchStatus.PROCESSING)
    done_old = make_batch(status=BatchStatus.COMPLETED)
    done_new = make_batch(status=BatchStatus.FAILED)

    store.save(running)
    store.save(done_old)
    store.save(done_new)

    assert store.get(running.batch_id) is running
    assert store.get(done_old.batch_id) is None
    assert store.get(done_new.batch_id) is done_new


def test_store_grows_past_limit_when_every_batch_is_processing():
    store = InMemoryBatchStore(max_batches=1)
    first, second = make_batch(), make_batch()

    store.save(first)
    store.save(second)

    assert store.get(first.batch_id) is first
    assert store.get(second.batch_id) is second


async def test_subscribe_streams_snapshots_until_terminal():
    store = InMemoryBatchStore(max_batches=10)
    batch = make_batch()
    store.save(batch)
    received = []

    async def consume():
        async for snapshot in store.subscribe(batch.batch_id):
            received.append(snapshot)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    batch.rows[0].status = RowStatus.CREATED
    batch.rows[0].hospital_id = 1
    store.save(batch)
    batch.status = BatchStatus.FAILED
    store.save(batch)
    await asyncio.wait_for(task, timeout=1)

    assert [s.status for s in received] == [
        BatchStatus.PROCESSING,
        BatchStatus.PROCESSING,
        BatchStatus.FAILED,
    ]
    assert received[1].processed_hospitals == 1


async def test_subscribe_to_finished_batch_yields_once():
    store = InMemoryBatchStore(max_batches=10)
    batch = make_batch(status=BatchStatus.COMPLETED)
    store.save(batch)

    snapshots = [snapshot async for snapshot in store.subscribe(batch.batch_id)]

    assert len(snapshots) == 1


async def test_subscribe_to_unknown_batch_yields_nothing():
    store = InMemoryBatchStore(max_batches=10)

    assert [snapshot async for snapshot in store.subscribe(uuid4())] == []
