from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from server.storage.db import db
from server.storage.image_store import image_store

router = APIRouter(prefix="/sessions", tags=["images"])


@router.get("/{session_id}/images/{topic:path}/{timestamp}")
async def get_image(session_id: str, topic: str, timestamp: float):
    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    topic_path = topic if topic.startswith("/") else f"/{topic}"

    row = await db.read_one(
        "SELECT image_path FROM messages "
        "WHERE session_id = ? AND topic = ? AND ABS(timestamp - ?) < 0.001 AND image_path IS NOT NULL "
        "LIMIT 1",
        [session_id, topic_path, timestamp],
    )

    if not row or not row.get("image_path"):
        raise HTTPException(status_code=404, detail="Image not found")

    image_bytes = image_store.load(row["image_path"])
    if not image_bytes:
        raise HTTPException(status_code=404, detail="Image file missing from disk")

    return Response(content=image_bytes, media_type="image/jpeg")
