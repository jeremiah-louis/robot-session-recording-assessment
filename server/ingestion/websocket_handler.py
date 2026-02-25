import json
import logging
import time
from typing import Dict

from fastapi import WebSocket, WebSocketDisconnect

from server.ingestion.buffer import SessionBuffer
from server.storage.db import db

logger = logging.getLogger(__name__)

# Active session buffers keyed by session_id
_active_buffers: Dict[str, SessionBuffer] = {}


async def handle_ingest(ws: WebSocket):
    await ws.accept()
    session_id = None
    buffer = None

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type")

            if msg_type == "session_start":
                session_id = msg["session_id"]
                await db.create_session({
                    "session_id": session_id,
                    "source": "live",
                    "robot_type": msg.get("robot_type"),
                    "fps": msg.get("fps"),
                    "start_time": time.time(),
                    "status": "recording",
                    "features": json.dumps(msg.get("topics")) if msg.get("topics") else None,
                })
                buffer = SessionBuffer(session_id)
                buffer.start()
                _active_buffers[session_id] = buffer
                logger.info("Session started: %s", session_id)

            elif msg_type == "message" and buffer:
                accepted = await buffer.put(msg)
                if not accepted:
                    await ws.send_json({"type": "backpressure", "action": "slow_down"})

            elif msg_type == "session_end" and session_id:
                await _finalize_session(session_id, buffer, "completed")
                logger.info("Session ended: %s", session_id)
                break

    except WebSocketDisconnect:
        if session_id:
            logger.warning("Client disconnected mid-session: %s", session_id)
            await _finalize_session(session_id, buffer, "disconnected")
    except Exception:
        logger.exception("Error in WS handler for session %s", session_id)
        if session_id:
            await _finalize_session(session_id, buffer, "disconnected")


async def _finalize_session(session_id: str, buffer: SessionBuffer, status: str):
    if buffer:
        await buffer.stop()
    _active_buffers.pop(session_id, None)

    # Count total frames and compute topic summaries
    row = await db.read_one(
        "SELECT COUNT(*) as cnt FROM messages WHERE session_id = ?", [session_id]
    )
    total_frames = row["cnt"] if row else 0

    await db.update_session(session_id, {
        "status": status,
        "end_time": time.time(),
        "total_frames": total_frames,
    })
    await db.compute_topic_summaries(session_id)
