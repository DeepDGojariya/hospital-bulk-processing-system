from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.deps import StoreDep

router = APIRouter(tags=["progress"])

BATCH_NOT_FOUND = 4404


@router.websocket("/hospitals/bulk/{batch_id}/ws")
async def batch_progress(websocket: WebSocket, batch_id: UUID, store: StoreDep) -> None:
    """Send a snapshot on every change, then close when the batch finishes."""
    await websocket.accept()
    if store.get(batch_id) is None:
        await websocket.close(code=BATCH_NOT_FOUND, reason="Batch not found")
        return
    try:
        async for snapshot in store.subscribe(batch_id):
            await websocket.send_text(snapshot.model_dump_json())
        await websocket.close()
    except WebSocketDisconnect:
        pass
