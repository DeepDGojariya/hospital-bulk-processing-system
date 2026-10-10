from uuid import uuid4

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.test_bulk_api import VALID_CSV, upload, wait_for_status


def failed_batch(client, directory) -> str:
    directory.script("create:City Clinic", 422)
    body = client.post("/hospitals/bulk", files=upload(VALID_CSV)).json()
    assert body["status"] == "failed"
    return body["batch_id"]


def test_resume_completes_a_failed_batch(client, directory):
    batch_id = failed_batch(client, directory)

    response = client.post(f"/hospitals/bulk/{batch_id}/resume")

    assert response.status_code == 200
    body = response.json()
    assert body["batch_id"] == batch_id
    assert body["status"] == "completed"
    assert body["batch_activated"] is True
    assert directory.create_calls("General Hospital") == 1
    assert directory.create_calls("City Clinic") == 2


def test_resume_async_returns_202(client, directory):
    batch_id = failed_batch(client, directory)

    response = client.post(f"/hospitals/bulk/{batch_id}/resume?mode=async")

    assert response.status_code == 202
    assert response.headers["location"] == f"/hospitals/bulk/{batch_id}"
    assert wait_for_status(client, batch_id, "completed")["batch_activated"] is True


def test_resume_unknown_batch_returns_404(client):
    response = client.post(f"/hospitals/bulk/{uuid4()}/resume")

    assert response.status_code == 404
    assert response.json() == {"detail": "Batch not found"}


def test_resume_completed_batch_returns_409(client):
    batch_id = client.post("/hospitals/bulk", files=upload(VALID_CSV)).json()["batch_id"]

    response = client.post(f"/hospitals/bulk/{batch_id}/resume")

    assert response.status_code == 409


def test_resume_while_processing_returns_409(client, directory):
    directory.delay = 0.3
    batch_id = client.post("/hospitals/bulk?mode=async", files=upload(VALID_CSV)).json()["batch_id"]

    response = client.post(f"/hospitals/bulk/{batch_id}/resume")

    assert response.status_code == 409
    wait_for_status(client, batch_id, "completed")


def test_resume_returns_502_when_reconciliation_fails(client, directory):
    batch_id = failed_batch(client, directory)
    directory.script("list", 500)

    response = client.post(f"/hospitals/bulk/{batch_id}/resume")

    assert response.status_code == 502
    assert client.get(f"/hospitals/bulk/{batch_id}").json()["status"] == "failed"


def test_websocket_streams_progress_until_completed(client, directory):
    directory.delay = 0.05
    batch_id = client.post("/hospitals/bulk?mode=async", files=upload(VALID_CSV)).json()["batch_id"]
    snapshots = []

    with client.websocket_connect(f"/hospitals/bulk/{batch_id}/ws") as websocket:
        with pytest.raises(WebSocketDisconnect):
            while True:
                snapshots.append(websocket.receive_json())

    assert len(snapshots) >= 2
    assert snapshots[0]["batch_id"] == batch_id
    assert snapshots[-1]["status"] == "completed"
    assert snapshots[-1]["processed_hospitals"] == 2


def test_websocket_for_finished_batch_sends_one_snapshot_and_closes(client):
    batch_id = client.post("/hospitals/bulk", files=upload(VALID_CSV)).json()["batch_id"]

    with client.websocket_connect(f"/hospitals/bulk/{batch_id}/ws") as websocket:
        assert websocket.receive_json()["status"] == "completed"
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()


def test_websocket_for_unknown_batch_closes_with_4404(client):
    with client.websocket_connect(f"/hospitals/bulk/{uuid4()}/ws") as websocket:
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_json()

    assert closed.value.code == 4404
