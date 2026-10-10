import asyncio
from contextlib import aclosing
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.deps import StoreDep
from app.store.base import BatchStore

router = APIRouter(tags=["progress"])

BATCH_NOT_FOUND = 4404


async def _send_snapshots(websocket: WebSocket, store: BatchStore, batch_id: UUID) -> None:
    # aclosing releases the subscription as soon as this task ends or is cancelled.
    async with aclosing(store.subscribe(batch_id)) as snapshots:
        async for snapshot in snapshots:
            await websocket.send_text(snapshot.model_dump_json())


async def _wait_for_disconnect(websocket: WebSocket) -> None:
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass


@router.websocket("/hospitals/bulk/{batch_id}/ws")
async def batch_progress(websocket: WebSocket, batch_id: UUID, store: StoreDep) -> None:
    """Send a snapshot on every change, then close when the batch finishes."""
    await websocket.accept()
    if store.get(batch_id) is None:
        await websocket.close(code=BATCH_NOT_FOUND, reason="Batch not found")
        return

    # Watch for the client leaving while we wait for progress; otherwise a
    # disconnect would only be noticed at the next snapshot.
    sender = asyncio.create_task(_send_snapshots(websocket, store, batch_id))
    watcher = asyncio.create_task(_wait_for_disconnect(websocket))
    try:
        await asyncio.wait({sender, watcher}, return_when=asyncio.FIRST_COMPLETED)
        finished = sender.done() and sender.exception() is None
    finally:
        sender.cancel()
        watcher.cancel()
        await asyncio.gather(sender, watcher, return_exceptions=True)
    if finished:
        await websocket.close()
