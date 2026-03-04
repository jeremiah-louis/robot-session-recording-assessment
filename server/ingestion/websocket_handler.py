import asyncio
import json
import logging
import time
from typing import Dict

from fastapi import WebSocket, WebSocketDisconnect

from server.errors import send_ws_error
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

            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning("Malformed JSON from client (session=%s): %s", session_id, exc)
                await send_ws_error(ws, "Invalid JSON message", code="invalid_json")
                continue

            msg_type = msg.get("type")

            if msg_type == "session_start":
                sid = msg.get("session_id")
                if not sid:
                    await send_ws_error(ws, "session_start requires 'session_id'", code="missing_field")
                    continue
                session_id = sid
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

            elif msg_type == "message":
                if not buffer:
                    await send_ws_error(ws, "Send 'session_start' before sending messages", code="no_session")
                    continue
                # Validate required fields
                missing = [f for f in ("topic", "timestamp") if f not in msg]
                if missing:
                    await send_ws_error(ws, f"Message missing required fields: {missing}", code="missing_field")
                    continue
                accepted = await buffer.put(msg)
                if not accepted:
                    await ws.send_json({"type": "backpressure", "action": "slow_down"})

            elif msg_type == "session_end" and session_id:
                await _finalize_session(session_id, buffer, "completed")
                logger.info("Session ended: %s", session_id)
                break

            else:
                await send_ws_error(ws, f"Unknown message type: {msg_type}", code="unknown_type")

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

    # Generate AI features in background — task stored so exceptions are not silently lost
    task = asyncio.create_task(_generate_ai_features(session_id))
    task.add_done_callback(lambda t: _handle_task_result(t, session_id))


def _handle_task_result(task: asyncio.Task, session_id: str) -> None:
    """Callback to log background task failures instead of losing them."""
    if task.cancelled():
        logger.info("AI feature task cancelled for session %s", session_id)
    elif exc := task.exception():
        logger.error("AI feature task failed for session %s: %s", session_id, exc, exc_info=exc)


async def _generate_ai_features(session_id: str):
    """Generate text summary, embedding, and metrics vector for a completed session."""
    from server.ai.embeddings import embed_session
    from server.ai.similarity import compute_metrics_vector

    try:
        await embed_session(session_id)
        await compute_metrics_vector(session_id)
        await db.update_session(session_id, {"ai_features_complete": True})
        logger.info("AI features generated for session %s", session_id)
    except Exception:
        logger.exception("AI feature generation failed for session %s", session_id)
        await db.update_session(session_id, {"ai_features_complete": False})
