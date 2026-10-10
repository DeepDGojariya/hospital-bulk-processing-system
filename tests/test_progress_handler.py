import asyncio
from uuid import uuid4

from starlette.websockets import WebSocketDisconnect

from app.api.progress import batch_progress
from app.store.base import BatchState, RowState
from app.store.memory import InMemoryBatchStore
from tests.fakes import make_rows


class FakeWebSocket:
    """Just enough of a WebSocket to drive the handler without a test client."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.client_left = asyncio.Event()
        self.closed_by_server = False

    async def accept(self) -> None:
        pass

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    async def receive_text(self) -> str:
        await self.client_left.wait()
        raise WebSocketDisconnect(1001)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed_by_server = True


async def test_handler_stops_and_unsubscribes_as_soon_as_the_client_leaves():
    store = InMemoryBatchStore(max_batches=10)
    batch = BatchState(batch_id=uuid4(), rows=[RowState(row=row) for row in make_rows(2)])
    store.save(batch)
    websocket = FakeWebSocket()

    handler = asyncio.create_task(batch_progress(websocket, batch.batch_id, store))
    await asyncio.sleep(0.01)
    assert len(websocket.sent) == 1
    assert len(store._subscribers) == 1

    websocket.client_left.set()
    await asyncio.wait_for(handler, timeout=1)

    assert store._subscribers == {}
    assert websocket.closed_by_server is False
