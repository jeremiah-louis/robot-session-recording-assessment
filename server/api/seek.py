from typing import List

from fastapi import APIRouter

from server.errors import NotFoundError
from server.storage.db import db
from server.storage.models import Message, SeekRequest

router = APIRouter(prefix="/sessions", tags=["seek"])


@router.post("/{session_id}/seek", response_model=List[Message])
async def seek(session_id: str, req: SeekRequest):
    session = await db.get_session(session_id)
    if not session:
        raise NotFoundError("Session", session_id)

    rows = await db.seek_messages(
        session_id,
        req.start_time,
        req.end_time,
        topics=req.topics,
        limit=req.limit,
    )
    return [Message(**r) for r in rows]
