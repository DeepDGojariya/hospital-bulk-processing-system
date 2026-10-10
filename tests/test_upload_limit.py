from app.config import Settings
from app.main import create_app

CHUNK = b"x" * 1024


def make_scope(headers: list[tuple[bytes, bytes]]) -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/hospitals/bulk",
        "raw_path": b"/hospitals/bulk",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }


async def post_raw(headers: list[tuple[bytes, bytes]], chunks: list[bytes]) -> tuple[int, int]:
    """Send a request straight to the ASGI app. Returns (status, chunks the app read)."""
    app = create_app(Settings(max_upload_bytes=2048))
    pulled = 0
    sent = []

    async def receive() -> dict:
        nonlocal pulled
        if pulled == len(chunks):
            return {"type": "http.disconnect"}
        pulled += 1
        return {
            "type": "http.request",
            "body": chunks[pulled - 1],
            "more_body": pulled < len(chunks),
        }

    async def send(message: dict) -> None:
        sent.append(message)

    await app(make_scope(headers), receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    return status, pulled


MULTIPART = (b"content-type", b"multipart/form-data; boundary=boundary")


async def test_declared_oversized_body_is_rejected_without_reading_it():
    status, pulled = await post_raw([MULTIPART, (b"content-length", b"52428800")], [CHUNK] * 100)

    assert status == 413
    assert pulled == 0


async def test_streamed_oversized_body_is_cut_off_early():
    preamble = (
        b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="h.csv"\r\n\r\n'
    )

    status, pulled = await post_raw([MULTIPART], [preamble] + [CHUNK] * 100)

    assert status == 413
    assert pulled < 20
