import asyncio
from collections import defaultdict
from typing import AsyncGenerator


class EventManager:
    """Async pub/sub hub for SSE. Subscribers get an asyncio.Queue per channel."""

    def __init__(self):
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)

    async def subscribe(self, channel: str) -> AsyncGenerator[str, None]:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[channel].append(queue)
        try:
            while True:
                data = await queue.get()
                yield data
        finally:
            self._subscribers[channel].remove(queue)

    async def publish(self, channel: str, data: str):
        for queue in self._subscribers[channel]:
            await queue.put(data)


event_manager = EventManager()
