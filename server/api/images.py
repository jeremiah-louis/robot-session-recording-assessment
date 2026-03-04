import logging

from fastapi import APIRouter
from fastapi.responses import Response

from server.errors import ImageStoreError, NotFoundError
from server.storage.db import db
from server.storage.image_store import image_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["images"])


@router.get("/{session_id}/images/{topic:path}/{timestamp}")
async def get_image(session_id: str, topic: str, timestamp: float):
    session = await db.get_session(session_id)
    if not session:
        raise NotFoundError("Session", session_id)

    topic_path = topic if topic.startswith("/") else f"/{topic}"

    row = await db.read_one(
        "SELECT image_path FROM messages "
        "WHERE session_id = ? AND topic = ? AND ABS(timestamp - ?) < 0.001 AND image_path IS NOT NULL "
        "LIMIT 1",
        [session_id, topic_path, timestamp],
    )

    if not row or not row.get("image_path"):
        raise NotFoundError("Image", f"session={session_id} topic={topic_path} t={timestamp}")

    try:
        image_bytes = image_store.load(row["image_path"])
    except ValueError as exc:
        logger.warning(
            "Path traversal blocked for session=%s topic=%s t=%s path=%r",
            session_id, topic_path, timestamp, row["image_path"],
        )
        raise ImageStoreError("Image path is invalid", detail="Path traversal blocked") from exc

    if not image_bytes:
        raise NotFoundError("Image file", "file missing from disk")

    return Response(content=image_bytes, media_type="image/jpeg")
