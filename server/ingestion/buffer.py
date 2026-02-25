import asyncio
import base64
import logging
from typing import List, Optional

from server.config import settings
from server.storage.db import db
from server.storage.image_store import image_store

logger = logging.getLogger(__name__)


class SessionBuffer:
    """Bounded buffer that batches telemetry messages and flushes to DuckDB."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=settings.buffer_max_size)
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False

    def start(self):
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def stop(self):
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self._drain()

    def is_full(self) -> bool:
        return self.queue.full()

    async def put(self, msg: dict) -> bool:
        """Add message to buffer. Returns False if queue is full (backpressure)."""
        try:
            self.queue.put_nowait(msg)
            return True
        except asyncio.QueueFull:
            return False

    async def _flush_loop(self):
        while self._running:
            await asyncio.sleep(settings.buffer_flush_interval)
            await self._drain(settings.buffer_flush_size)

    async def _drain(self, max_items: Optional[int] = None):
        """Drain up to max_items from the queue and insert them. Drains all if max_items is None."""
        batch: List[list] = []
        while max_items is None or len(batch) < max_items:
            try:
                msg = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            row = self._msg_to_row(msg)
            if row:
                batch.append(row)

        if batch:
            try:
                await db.insert_messages(batch)
            except Exception:
                logger.exception("Failed to flush %d messages for session %s", len(batch), self.session_id)

    def _msg_to_row(self, msg: dict) -> Optional[list]:
        """Convert a raw WS message dict to a DB row."""
        image_path = None
        data = msg.get("data")

        if msg.get("image_base64"):
            try:
                image_bytes = base64.b64decode(msg["image_base64"])
                image_path = image_store.save(
                    self.session_id, msg["topic"], msg["timestamp"], image_bytes
                )
                data = None
            except Exception:
                logger.exception("Failed to decode image for session %s", self.session_id)
                return None

        msg_id = db.next_msg_id()
        return [
            msg_id,
            self.session_id,
            msg["timestamp"],
            msg["topic"],
            msg["data_type"],
            str(data) if data is not None else None,
            image_path,
            msg.get("frame_index"),
        ]
