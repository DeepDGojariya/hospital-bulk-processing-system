import asyncio

import httpx
import pytest

from app.schemas import BatchStatus, RowStatus
from tests.fakes import make_rows


async def test_run_creates_every_row_and_activates(processor, directory, store):
    batch = processor.create_batch(make_rows(3))

    result = await processor.run(batch)

    assert result.status is BatchStatus.COMPLETED
    assert result.batch_activated is True
    assert result.total_hospitals == 3
    assert result.processed_hospitals == 3
    assert result.failed_hospitals == 0
    assert result.processing_time_seconds >= 0
    assert [h.status for h in result.hospitals] == [RowStatus.CREATED_AND_ACTIVATED] * 3
    assert sorted(h.hospital_id for h in result.hospitals) == [101, 102, 103]
    assert directory.activate_calls() == 1
    assert all(h["creation_batch_id"] == str(batch.batch_id) for h in directory.hospitals)
    assert all(h["active"] for h in directory.hospitals)
    assert store.get(batch.batch_id) is batch


async def test_new_batch_starts_processing_with_pending_rows(processor):
    result = processor.create_batch(make_rows(2)).to_result()

    assert result.status is BatchStatus.PROCESSING
    assert [h.status for h in result.hospitals] == [RowStatus.PENDING] * 2


async def test_failed_row_prevents_activation(processor, directory):
    directory.script("create:H2", 422)
    batch = processor.create_batch(make_rows(3))

    result = await processor.run(batch)

    assert result.status is BatchStatus.FAILED
    assert result.batch_activated is False
    assert result.processed_hospitals == 2
    assert result.failed_hospitals == 1
    assert [h.status for h in result.hospitals] == [
        RowStatus.CREATED,
        RowStatus.FAILED,
        RowStatus.CREATED,
    ]
    assert "422" in result.hospitals[1].error
    assert result.hospitals[1].hospital_id is None
    assert directory.activate_calls() == 0


async def test_activation_failure_leaves_rows_created(processor, directory):
    directory.script("activate", 500)
    batch = processor.create_batch(make_rows(2))

    result = await processor.run(batch)

    assert result.status is BatchStatus.FAILED
    assert result.batch_activated is False
    assert "500" in result.activation_error
    assert result.failed_hospitals == 0
    assert [h.status for h in result.hospitals] == [RowStatus.CREATED] * 2


async def test_upstream_calls_run_concurrently_within_the_limit(processor, directory):
    directory.delay = 0.01
    batch = processor.create_batch(make_rows(10))

    await processor.run(batch)

    assert 1 < directory.max_in_flight <= 3


async def test_concurrency_limit_is_shared_across_batches(processor, directory):
    directory.delay = 0.01
    first = processor.create_batch(make_rows(5))
    second = processor.create_batch(make_rows(5))

    await asyncio.gather(processor.run(first), processor.run(second))

    assert directory.max_in_flight <= 3


async def test_unexpected_error_does_not_leave_batch_processing(processor, upstream, monkeypatch):
    async def boom(row, batch_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(upstream, "create_hospital", boom)
    batch = processor.create_batch(make_rows(2))

    with pytest.raises(ExceptionGroup):
        await processor.run(batch)

    assert batch.status is BatchStatus.FAILED


async def test_run_in_background_completes_the_batch(processor):
    batch = processor.create_batch(make_rows(2))

    processor.run_in_background(batch)
    for _ in range(100):
        if batch.status is not BatchStatus.PROCESSING:
            break
        await asyncio.sleep(0.01)

    assert batch.status is BatchStatus.COMPLETED


async def test_unreachable_upstream_fails_every_row_without_sending_creates(processor, directory):
    directory.script("ping", 503, 503, 503)
    batch = processor.create_batch(make_rows(3))

    result = await processor.run(batch)

    assert result.status is BatchStatus.FAILED
    assert result.failed_hospitals == 3
    assert all("503" in h.error for h in result.hospitals)
    assert directory.create_calls() == 0
    assert directory.activate_calls() == 0


async def test_run_waits_for_a_cold_upstream_before_creating(processor, directory):
    directory.script("ping", httpx.ReadTimeout("cold start"))
    batch = processor.create_batch(make_rows(2))

    result = await processor.run(batch)

    assert result.status is BatchStatus.COMPLETED
    assert [request.url.path for request in directory.requests[:2]] == ["/", "/"]
    assert directory.create_calls() == 2
