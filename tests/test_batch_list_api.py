from datetime import datetime

from tests.test_bulk_api import VALID_CSV, upload


def test_list_is_empty_before_any_upload(client):
    response = client.get("/hospitals/bulk")

    assert response.status_code == 200
    assert response.json() == []


def test_list_summarises_each_batch(client):
    created = client.post("/hospitals/bulk", files=upload(VALID_CSV)).json()

    [summary] = client.get("/hospitals/bulk").json()

    started = datetime.fromisoformat(summary.pop("created_at"))
    assert started.tzinfo is not None
    assert summary == {
        "batch_id": created["batch_id"],
        "status": "completed",
        "total_hospitals": 2,
        "processed_hospitals": 2,
        "failed_hospitals": 0,
        "processing_time_seconds": created["processing_time_seconds"],
        "batch_activated": True,
    }


def test_list_is_newest_first_and_includes_failed_batches(client, directory):
    first = client.post("/hospitals/bulk", files=upload(VALID_CSV)).json()
    directory.script("create:City Clinic", 422)
    second = client.post("/hospitals/bulk", files=upload(VALID_CSV)).json()

    batches = client.get("/hospitals/bulk").json()

    assert [b["batch_id"] for b in batches] == [second["batch_id"], first["batch_id"]]
    assert [b["status"] for b in batches] == ["failed", "completed"]
    assert batches[0]["failed_hospitals"] == 1


def test_single_batch_response_keeps_its_shape(client):
    created = client.post("/hospitals/bulk", files=upload(VALID_CSV)).json()

    assert "created_at" not in created
