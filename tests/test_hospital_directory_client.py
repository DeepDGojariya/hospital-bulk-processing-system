import json
from uuid import uuid4

import httpx
import pytest

from app.clients.hospital_directory import UpstreamError, UpstreamHospital
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
