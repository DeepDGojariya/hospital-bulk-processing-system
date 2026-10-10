import re


def test_root_serves_the_upload_page(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<h1>Hospital Bulk Upload</h1>" in response.text


def test_every_asset_the_page_references_is_served(client):
    page = client.get("/").text

    assets = re.findall(r'(?:src|href)="(/static/[^"]+)"', page)

    assert sorted(assets) == ["/static/app.js", "/static/styles.css"]
    for asset in assets:
        assert client.get(asset).status_code == 200, asset


def test_page_is_not_listed_in_the_api_schema(client):
    paths = client.get("/openapi.json").json()["paths"]

    assert "/" not in paths
    assert "/hospitals/bulk" in paths
