import asyncio

import pytest

from app.schemas import BatchStatus, HospitalRow, RowStatus
from app.services.processor import BatchNotResumable, ReconciliationError
from tests.fakes import TIMEOUT_AFTER_CREATE, make_rows


async def test_resume_retries_only_failed_rows_and_activates(processor, directory):
    directory.script("create:H2", 503, 503, 503)
    batch = processor.create_batch(make_rows(3))
    assert (await processor.run(batch)).status is BatchStatus.FAILED

    await processor.prepare_resume(batch)
    result = await processor.run(batch)

    assert result.status is BatchStatus.COMPLETED
    assert result.batch_activated is True
    assert result.failed_hospitals == 0
    assert [h.status for h in result.hospitals] == [RowStatus.CREATED_AND_ACTIVATED] * 3
    assert all(h.error is None for h in result.hospitals)
    assert directory.create_calls("H1") == 1
    assert directory.create_calls("H2") == 4
    assert directory.create_calls("H3") == 1


async def test_prepare_resume_resets_failed_rows_to_pending(processor, directory):
    directory.script("create:H1", 422)
    batch = processor.create_batch(make_rows(2))
    await processor.run(batch)

    await processor.prepare_resume(batch)

    result = batch.to_result()
    assert result.status is BatchStatus.PROCESSING
    assert result.failed_hospitals == 0
    assert result.hospitals[0].status is RowStatus.PENDING
    assert result.hospitals[0].error is None
    assert result.hospitals[1].status is RowStatus.CREATED


async def test_resume_reconciles_row_created_upstream_despite_timeout(processor, directory):
    directory.script("create:H2", TIMEOUT_AFTER_CREATE)
    batch = processor.create_batch(make_rows(3))
    failed = await processor.run(batch)
    assert failed.hospitals[1].status is RowStatus.FAILED

    await processor.prepare_resume(batch)
    result = await processor.run(batch)

    assert result.status is BatchStatus.COMPLETED
    assert directory.create_calls("H2") == 1
    assert len(directory.hospitals) == 3
    upstream_id = next(h["id"] for h in directory.hospitals if h["name"] == "H2")
    assert result.hospitals[1].hospital_id == upstream_id


async def test_reconciliation_matches_identical_rows_one_to_one(processor, directory):
    twin = {"name": "Twin", "address": "9 Same St", "phone": "555"}
    rows = [HospitalRow(row=1, **twin), HospitalRow(row=2, **twin)]
    directory.script("create:Twin", TIMEOUT_AFTER_CREATE, 422)
    batch = processor.create_batch(rows)
    await processor.run(batch)

    await processor.prepare_resume(batch)
    result = await processor.run(batch)

    assert result.status is BatchStatus.COMPLETED
    assert len(directory.hospitals) == 2
    assert len({h.hospital_id for h in result.hospitals}) == 2


async def test_resume_after_activation_failure_only_activates(processor, directory):
    directory.script("activate", 500)
    batch = processor.create_batch(make_rows(2))
    await processor.run(batch)

    await processor.prepare_resume(batch)
    result = await processor.run(batch)

    assert result.status is BatchStatus.COMPLETED
    assert result.activation_error is None
    assert directory.create_calls() == 2
    assert directory.activate_calls() == 2


async def test_resume_works_when_upstream_has_no_hospitals_for_the_batch(processor, directory):
    directory.script("create:H1", 422)
    directory.script("create:H2", 422)
    batch = processor.create_batch(make_rows(2))
    await processor.run(batch)
    assert directory.hospitals == []

    await processor.prepare_resume(batch)
    result = await processor.run(batch)

    assert result.status is BatchStatus.COMPLETED


async def test_completed_batch_is_not_resumable(processor):
    batch = processor.create_batch(make_rows(1))
    await processor.run(batch)

    with pytest.raises(BatchNotResumable):
        await processor.prepare_resume(batch)


async def test_processing_batch_is_not_resumable(processor):
    batch = processor.create_batch(make_rows(1))

    with pytest.raises(BatchNotResumable):
        await processor.prepare_resume(batch)


async def test_failed_reconciliation_leaves_batch_failed_and_unchanged(processor, directory):
    directory.script("create:H1", 422)
    batch = processor.create_batch(make_rows(2))
    await processor.run(batch)
    before = batch.to_result()
    directory.script("list", 500)

    with pytest.raises(ReconciliationError):
        await processor.prepare_resume(batch)

    assert batch.to_result() == before
    assert batch.status is BatchStatus.FAILED


async def test_failed_reconciliation_releases_progress_subscribers(processor, directory, store):
    directory.script("create:H1", 422)
    batch = processor.create_batch(make_rows(2))
    await processor.run(batch)
    directory.script("list", 500)
    directory.blocked = True
    received = []

    async def consume():
        async for snapshot in store.subscribe(batch.batch_id):
            received.append(snapshot)

    resume = asyncio.create_task(processor.prepare_resume(batch))
    await asyncio.sleep(0.01)
    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    assert received[0].status is BatchStatus.PROCESSING
    directory.blocked = False

    with pytest.raises(ReconciliationError):
        await resume
    await asyncio.wait_for(consumer, timeout=1)

    assert received[-1].status is BatchStatus.FAILED


async def test_unexpected_error_during_resume_does_not_leave_batch_processing(
    processor, directory, upstream, monkeypatch
):
    directory.script("create:H1", 422)
    batch = processor.create_batch(make_rows(2))
    await processor.run(batch)

    async def boom(batch_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(upstream, "list_batch", boom)

    with pytest.raises(RuntimeError):
        await processor.prepare_resume(batch)

    assert batch.status is BatchStatus.FAILED


async def test_reconciliation_tolerates_blank_phone_and_padding_from_upstream(processor, directory):
    directory.script("create:H2", TIMEOUT_AFTER_CREATE)
    batch = processor.create_batch(make_rows(2))
    await processor.run(batch)
    stored = next(h for h in directory.hospitals if h["name"] == "H2")
    stored["phone"] = ""
    stored["name"] = "H2 "

    await processor.prepare_resume(batch)
    result = await processor.run(batch)

    assert result.status is BatchStatus.COMPLETED
    assert directory.create_calls("H2") == 1
