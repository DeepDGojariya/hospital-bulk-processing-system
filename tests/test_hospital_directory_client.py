import asyncio
import json
import logging
from uuid import uuid4

import httpx
import pytest

from app.clients.hospital_directory import (
    HospitalDirectoryClient,
    UpstreamError,
    UpstreamHospital,
)
from app.schemas import HospitalRow

ROW = HospitalRow(row=1, name="General", address="1 Main St", phone="555-1")


async def test_create_sends_payload_and_returns_id(upstream, directory):
    batch_id = uuid4()

    hospital_id = await upstream.create_hospital(ROW, batch_id)

    assert hospital_id == 101
    assert json.loads(directory.requests[0].content) == {
        "name": "General",
        "address": "1 Main St",
        "phone": "555-1",
        "creation_batch_id": str(batch_id),
    }


@pytest.mark.parametrize("status", [429, 502, 503, 504])
async def test_create_retries_transient_status_then_succeeds(upstream, directory, sleeps, status):
    directory.script("create:General", status)

    assert await upstream.create_hospital(ROW, uuid4()) == 101
    assert directory.create_calls() == 2
    assert len(sleeps) == 1


async def test_create_retries_connection_errors(upstream, directory):
    directory.script("create:General", httpx.ConnectError("refused"))

    assert await upstream.create_hospital(ROW, uuid4()) == 101
    assert directory.create_calls() == 2


async def test_backoff_grows_between_attempts(upstream, directory, sleeps):
    directory.script("create:General", 503, 503)

    await upstream.create_hospital(ROW, uuid4())

    assert 0.5 <= sleeps[0] <= 1.0
    assert 1.0 <= sleeps[1] <= 1.5


async def test_create_gives_up_after_max_retries(upstream, directory):
    directory.script("create:General", 503, 503, 503)

    with pytest.raises(UpstreamError) as raised:
        await upstream.create_hospital(ROW, uuid4())

    assert raised.value.status_code == 503
    assert directory.create_calls() == 3


async def test_create_does_not_retry_client_errors(upstream, directory):
    directory.script("create:General", 422)

    with pytest.raises(UpstreamError) as raised:
        await upstream.create_hospital(ROW, uuid4())

    assert raised.value.status_code == 422
    assert "422" in str(raised.value)
    assert directory.create_calls() == 1


async def test_create_does_not_retry_read_timeout(upstream, directory):
    directory.script("create:General", httpx.ReadTimeout("slow"))

    with pytest.raises(UpstreamError):
        await upstream.create_hospital(ROW, uuid4())

    assert directory.create_calls() == 1


async def test_create_fails_cleanly_on_unexpected_success_body(upstream, directory):
    directory.script("create:General", httpx.Response(200, text="<html>error</html>"))

    with pytest.raises(UpstreamError, match="unexpected"):
        await upstream.create_hospital(ROW, uuid4())


async def test_activate_retries_read_timeout(upstream, directory):
    directory.script("activate", httpx.ReadTimeout("slow"))

    await upstream.activate_batch(uuid4())

    assert directory.activate_calls() == 2


async def test_list_batch_returns_hospitals(upstream, directory):
    batch_id = uuid4()
    await upstream.create_hospital(ROW, batch_id)

    assert await upstream.list_batch(batch_id) == [
        UpstreamHospital(id=101, name="General", address="1 Main St", phone="555-1")
    ]


async def test_list_batch_treats_404_as_empty(upstream):
    assert await upstream.list_batch(uuid4()) == []


async def test_list_batch_raises_on_server_error(upstream, directory):
    directory.script("list", 500)

    with pytest.raises(UpstreamError):
        await upstream.list_batch(uuid4())


async def test_ping_succeeds_when_upstream_is_up(upstream, directory):
    await upstream.ping()

    assert [request.url.path for request in directory.requests] == ["/"]


async def test_ping_retries_read_timeout_from_a_cold_upstream(upstream, directory):
    directory.script("ping", httpx.ReadTimeout("cold start"))

    await upstream.ping()

    assert len(directory.requests) == 2


async def test_ping_raises_when_upstream_stays_down(upstream, directory):
    directory.script("ping", 503, 503, 503)

    with pytest.raises(UpstreamError):
        await upstream.ping()


async def test_retry_waits_at_least_as_long_as_retry_after(upstream, directory, sleeps):
    directory.script("create:General", httpx.Response(429, headers={"Retry-After": "7"}))

    await upstream.create_hospital(ROW, uuid4())

    assert sleeps == [7.0]


async def test_retry_after_is_capped(upstream, directory, sleeps):
    directory.script("create:General", httpx.Response(429, headers={"Retry-After": "86400"}))

    await upstream.create_hospital(ROW, uuid4())

    assert sleeps == [30.0]


async def test_retries_are_logged(upstream, directory, caplog):
    directory.script("create:General", 503)

    with caplog.at_level(logging.WARNING):
        await upstream.create_hospital(ROW, uuid4())

    assert any("Retrying POST /hospitals/" in record.getMessage() for record in caplog.records)


async def test_backoff_does_not_hold_a_concurrency_slot(directory):
    backoff_over = asyncio.Event()

    async def sleep_until_released(seconds: float) -> None:
        await backoff_over.wait()

    async with httpx.AsyncClient(
        base_url="http://directory.test", transport=httpx.MockTransport(directory)
    ) as http:
        client = HospitalDirectoryClient(
            http, max_retries=3, backoff_seconds=0.5, max_concurrency=1, sleep=sleep_until_released
        )
        directory.script("create:General", 503)
        retrying = asyncio.create_task(client.create_hospital(ROW, uuid4()))
        await asyncio.sleep(0.01)

        other = HospitalRow(row=2, name="Other", address="2 Oak Ave")
        other_id = await asyncio.wait_for(client.create_hospital(other, uuid4()), timeout=1)
        backoff_over.set()

        assert other_id == 101
        assert await retrying == 102
