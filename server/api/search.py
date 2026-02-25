import logging

from fastapi import APIRouter, HTTPException, Query

from server.ai.search import find_similar_sessions, search_sessions
from server.ai.similarity import get_similarity_graph
from server.storage.db import db
from server.storage.models import (
    SearchRequest,
    SearchResult,
    Session,
    SimilarityGraphResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["search"])


@router.post("/sessions/search", response_model=list[SearchResult])
async def nl_search(request: SearchRequest):
    """Natural language search over session summaries using embeddings."""
    rows = await search_sessions(request.query, request.limit)

    results = []
    for row in rows:
        score = row.pop("score", 0.0)
        # Remove fields not in Session model
        row.pop("embedding", None)
        row.pop("metrics_vec", None)
        results.append(SearchResult(session=Session(**row), score=score))

    return results


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

    results = []
    for row in rows:
        score = row.pop("score", 0.0)
        row.pop("embedding", None)
        row.pop("metrics_vec", None)
        results.append(SearchResult(session=Session(**row), score=score))

    return results
