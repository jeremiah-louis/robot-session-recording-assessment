from typing import List

from fastapi import APIRouter

from server.errors import NotFoundError
from server.storage.db import db
from server.storage.models import TopicSummary

router = APIRouter(prefix="/sessions", tags=["topics"])


@router.get("/{session_id}/topics", response_model=List[TopicSummary])
async def get_topics(session_id: str):
    session = await db.get_session(session_id)
    if not session:
        raise NotFoundError("Session", session_id)
    rows = await db.get_topics(session_id)
    return [TopicSummary(**r) for r in rows]
