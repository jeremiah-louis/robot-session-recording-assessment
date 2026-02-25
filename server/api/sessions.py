import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from server.storage.db import db
from server.storage.models import Session, SessionListResponse

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _parse_features(raw: object) -> Optional[dict]:
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


_EXCLUDED_FIELDS = {"embedding", "metrics_vec"}


def _row_to_session(row: dict) -> Session:
    cleaned = {k: v for k, v in row.items() if k not in _EXCLUDED_FIELDS}
    if cleaned.get("created_at"):
        cleaned["created_at"] = str(cleaned["created_at"])
    cleaned["features"] = _parse_features(cleaned.get("features"))
    return Session(**cleaned)


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    source: Optional[str] = Query(None, description="Filter by source: 'live' or 'import'"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    rows = await db.list_sessions(source=source, limit=limit, offset=offset)
    total = await db.count_sessions(source=source)
    return SessionListResponse(
        sessions=[_row_to_session(r) for r in rows],
        total=total,
    )


@router.get("/{session_id}", response_model=Session)
async def get_session(session_id: str):
    row = await db.get_session(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    return _row_to_session(row)
