import logging
from typing import Any, Dict, List

from server.ai.embeddings import generate_embedding
from server.storage.db import db

logger = logging.getLogger(__name__)


async def search_sessions(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Search sessions using natural language query via cosine similarity on embeddings."""
    query_embedding = await generate_embedding(query)

    # DuckDB supports list_cosine_similarity for vector operations
    rows = await db.read(
        """
        SELECT *,
            list_cosine_similarity(embedding, ?::FLOAT[1536]) as score
        FROM sessions
        WHERE embedding IS NOT NULL
        ORDER BY score DESC
        LIMIT ?
        """,
        [query_embedding, limit],
    )

    return rows


async def find_similar_sessions(
    session_id: str, limit: int = 10
) -> List[Dict[str, Any]]:
    """Find sessions similar to a given session using embedding cosine similarity."""
    session = await db.get_session(session_id)
    if not session or not session.get("embedding"):
        return []

    embedding = session["embedding"]

    rows = await db.read(
        """
        SELECT *,
            list_cosine_similarity(embedding, ?::FLOAT[1536]) as score
        FROM sessions
        WHERE embedding IS NOT NULL
            AND session_id != ?
        ORDER BY score DESC
        LIMIT ?
        """,
        [embedding, session_id, limit],
    )

    return rows
