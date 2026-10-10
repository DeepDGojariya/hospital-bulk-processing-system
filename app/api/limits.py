"""Reject oversized request bodies while they arrive, before anything is buffered."""

from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Room for multipart boundaries and part headers around the file itself.
MULTIPART_OVERHEAD_BYTES = 8192


class MaxBodySizeMiddleware:
    """Without this, the multipart parser spools the whole upload to disk first."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self._app = app
        self._max_bytes = max_bytes
        self._detail = f"Request body exceeds the {max_bytes} byte limit"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        declared = Headers(scope=scope).get("content-length", "")
        if declared.isdigit() and int(declared) > self._max_bytes:
            response = JSONResponse({"detail": self._detail}, status_code=413)
            await response(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            # Covers chunked uploads, which declare no length up front.
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max_bytes:
                    raise HTTPException(413, self._detail)
            return message

        await self._app(scope, limited_receive, send)
