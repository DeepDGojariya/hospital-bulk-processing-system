import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def built_ui(tmp_path):
    """A stand-in for the output of the front-end build."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>Hospital Bulk Upload</title>")
    (tmp_path / "assets" / "app.js").write_text("console.log('ui')")
    return tmp_path


def make_client(directory, ui_dir) -> TestClient:
    settings = Settings(hospital_api_base_url="http://directory.test", ui_dir=ui_dir)
    return TestClient(create_app(settings, transport=httpx.MockTransport(directory)))


def test_root_serves_the_built_page(directory, built_ui):
    with make_client(directory, built_ui) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Hospital Bulk Upload" in response.text


def test_built_assets_are_served(directory, built_ui):
    with make_client(directory, built_ui) as client:
        response = client.get("/assets/app.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


def test_root_explains_how_to_build_the_ui_when_it_is_missing(directory, tmp_path):
    with make_client(directory, tmp_path / "not-built") as client:
        response = client.get("/")
        api_still_works = client.get("/health").status_code

    assert response.status_code == 503
    assert "npm run build" in response.json()["detail"]
    assert api_still_works == 200


def test_page_is_not_listed_in_the_api_schema(directory, built_ui):
    with make_client(directory, built_ui) as client:
        paths = client.get("/openapi.json").json()["paths"]

    assert "/" not in paths
    assert "/hospitals/bulk" in paths
