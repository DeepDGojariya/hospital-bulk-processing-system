import time
from uuid import UUID, uuid4

VALID_CSV = "name,address,phone\nGeneral Hospital,1 Main St,555-1\nCity Clinic,2 Oak Ave,\n"


def upload(content: str | bytes) -> dict:
    return {"file": ("hospitals.csv", content, "text/csv")}


def wait_for_status(client, batch_id: str, status: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/hospitals/bulk/{batch_id}").json()
        if body["status"] == status:
            return body
        time.sleep(0.01)
    raise AssertionError(f"batch {batch_id} never reached {status}: {body}")


def test_bulk_create_returns_the_assignment_response_shape(client, directory):
    response = client.post("/hospitals/bulk", files=upload(VALID_CSV))

    assert response.status_code == 200
    body = response.json()
    UUID(body["batch_id"])
    assert isinstance(body["processing_time_seconds"], float)
    assert body == {
        "batch_id": body["batch_id"],
        "status": "completed",
        "total_hospitals": 2,
        "processed_hospitals": 2,
        "failed_hospitals": 0,
        "processing_time_seconds": body["processing_time_seconds"],
        "batch_activated": True,
        "activation_error": None,
        "hospitals": [
            {
                "row": 1,
                "hospital_id": body["hospitals"][0]["hospital_id"],
                "name": "General Hospital",
                "status": "created_and_activated",
                "error": None,
            },
            {
                "row": 2,
                "hospital_id": body["hospitals"][1]["hospital_id"],
                "name": "City Clinic",
                "status": "created_and_activated",
                "error": None,
            },
        ],
    }
    assert {h["hospital_id"] for h in body["hospitals"]} == {101, 102}
    assert all(h["creation_batch_id"] == body["batch_id"] for h in directory.hospitals)


def test_partial_failure_returns_200_with_failed_status(client, directory):
    directory.script("create:City Clinic", 422)

    response = client.post("/hospitals/bulk", files=upload(VALID_CSV))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["batch_activated"] is False
    assert body["failed_hospitals"] == 1
    assert body["hospitals"][1]["status"] == "failed"


def test_invalid_csv_returns_422_and_makes_no_upstream_calls(client, directory):
    response = client.post("/hospitals/bulk", files=upload("name,address\n,1 Main St\n"))

    assert response.status_code == 422
    assert response.json() == {
        "detail": "CSV validation failed",
        "errors": [{"row": 1, "field": "name", "message": "name is required"}],
    }
    assert directory.requests == []


def test_more_than_twenty_rows_is_rejected(client, directory):
    content = "name,address\n" + "H,A\n" * 21

    response = client.post("/hospitals/bulk", files=upload(content))

    assert response.status_code == 422
    assert response.json()["errors"][0]["message"] == "CSV has 21 rows; the maximum is 20"
    assert directory.requests == []


def test_oversized_upload_returns_413(client, directory):
    response = client.post("/hospitals/bulk", files=upload("name,address\n" + "x" * 3000))

    assert response.status_code == 413
    assert directory.requests == []


def test_missing_file_field_returns_422_in_the_same_shape_as_csv_errors(client):
    response = client.post("/hospitals/bulk")

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Request validation failed",
        "errors": [{"row": None, "field": "file", "message": "Field required"}],
    }


def test_unknown_mode_returns_422(client, directory):
    response = client.post("/hospitals/bulk?mode=later", files=upload(VALID_CSV))

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "mode"
    assert directory.requests == []


def test_malformed_batch_id_returns_422_naming_the_field(client):
    response = client.get("/hospitals/bulk/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["detail"] == "Request validation failed"
    assert response.json()["errors"][0]["field"] == "batch_id"


def test_async_mode_returns_202_and_finishes_in_background(client):
    response = client.post("/hospitals/bulk?mode=async", files=upload(VALID_CSV))

    assert response.status_code == 202
    body = response.json()
    assert body["total_hospitals"] == 2
    assert response.headers["location"] == f"/hospitals/bulk/{body['batch_id']}"
    final = wait_for_status(client, body["batch_id"], "completed")
    assert final["batch_activated"] is True
    assert final["processed_hospitals"] == 2


def test_status_endpoint_returns_stored_result(client):
    created = client.post("/hospitals/bulk", files=upload(VALID_CSV)).json()

    response = client.get(f"/hospitals/bulk/{created['batch_id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_status_endpoint_returns_404_for_unknown_batch(client):
    response = client.get(f"/hospitals/bulk/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Batch not found"}


def test_validate_reports_a_valid_file_without_upstream_calls(client, directory):
    response = client.post("/hospitals/bulk/validate", files=upload(VALID_CSV))

    assert response.status_code == 200
    assert response.json() == {"valid": True, "total_rows": 2, "errors": []}
    assert directory.requests == []


def test_validate_reports_errors_with_200(client):
    response = client.post("/hospitals/bulk/validate", files=upload("name,address\nA,\n"))

    assert response.status_code == 200
    assert response.json() == {
        "valid": False,
        "total_rows": 1,
        "errors": [{"row": 1, "field": "address", "message": "address is required"}],
    }


def test_validate_rejects_oversized_upload(client):
    response = client.post("/hospitals/bulk/validate", files=upload("name,address\n" + "x" * 3000))

    assert response.status_code == 413
