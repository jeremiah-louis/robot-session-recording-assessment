import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from server.storage.db import db

router = APIRouter(prefix="/sessions", tags=["export"])

_EXCLUDED_FIELDS = {"embedding", "metrics_vec"}

# Remove non-serializable fields from session dictionary
def _clean_session_dict(session: dict) -> dict:
    cleaned = {k: v for k, v in session.items() if k not in _EXCLUDED_FIELDS}
    if cleaned.get("created_at"):
        cleaned["created_at"] = str(cleaned["created_at"])
    return cleaned


@router.get("/{session_id}/export")
async def export_session(session_id: str):
    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = await db.read(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY timestamp ASC",
        [session_id],
    )
    topics = await db.get_topics(session_id)

    export_data = {
        "session": _clean_session_dict(session),
        "topics": topics,
        "messages": messages,
    }

    return Response(
        content=json.dumps(export_data, default=str, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={session_id}.json"},
    )
