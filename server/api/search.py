from fastapi import APIRouter, HTTPException, Query

from server.ai.search import find_similar_sessions, search_sessions
from server.ai.similarity import get_similarity_graph
from server.api.sessions import _row_to_session
from server.storage.db import db
from server.storage.models import (
    SearchRequest,
    SearchResult,
    SimilarityGraphResponse,
)

router = APIRouter(tags=["search"])


def _row_to_search_result(row: dict) -> SearchResult:
    """Convert a DB row with a 'score' column to a SearchResult."""
    score = row.pop("score", 0.0)
    return SearchResult(session=_row_to_session(row), score=score)


@router.post("/sessions/search", response_model=list[SearchResult])
async def nl_search(request: SearchRequest):
    """Natural language search over session summaries using embeddings."""
    rows = await search_sessions(request.query, request.limit)
    return [_row_to_search_result(row) for row in rows]


@router.get("/sessions/similarity-graph", response_model=SimilarityGraphResponse)
async def similarity_graph():
    """Get the full similarity graph for visualization."""
    graph = await get_similarity_graph()
    return SimilarityGraphResponse(**graph)


@router.get("/sessions/{session_id}/similar", response_model=list[SearchResult])
async def similar_sessions(
    session_id: str,
    limit: int = Query(default=10, ge=1, le=100),
):
    """Find sessions similar to a given session."""
    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    rows = await find_similar_sessions(session_id, limit)
    return [_row_to_search_result(row) for row in rows]
