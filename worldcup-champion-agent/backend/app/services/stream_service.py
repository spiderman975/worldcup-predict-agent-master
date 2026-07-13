import asyncio
import json
from collections import defaultdict
from typing import Any, AsyncGenerator


class StreamService:
    """内存级 SSE 事件中心，每个 run_id 对应一个队列。"""

    def __init__(self) -> None:
        self.queues: dict[str, asyncio.Queue[dict[str, Any]]] = defaultdict(asyncio.Queue)
        self.subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    async def publish(self, run_id: str, event: str, message: str, phase: str | None = None, data: dict[str, Any] | None = None) -> None:
        """向指定任务推送事件。"""

        payload = {"event": event, "run_id": run_id, "phase": phase, "message": message, "data": data or {}}
        await self.queues[run_id].put(payload)
        for queue in list(self.subscribers.get(run_id, set())):
            await queue.put(payload)

    def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any]]:
        """Create an additional listener queue without consuming the main SSE stream."""

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.subscribers[run_id].add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove a secondary listener queue."""

        self.subscribers.get(run_id, set()).discard(queue)

    async def stream(self, run_id: str) -> AsyncGenerator[dict[str, str], None]:
        """生成 sse-starlette 需要的事件字典。"""

        queue = self.queues[run_id]
        while True:
            payload = await queue.get()
            yield {"event": payload["event"], "data": json.dumps(payload, ensure_ascii=False)}
            if payload["event"] in {"prediction_complete", "prediction_error", "prediction_canceled"}:
                break


stream_service = StreamService()
