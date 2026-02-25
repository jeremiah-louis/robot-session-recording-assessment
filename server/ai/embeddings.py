import json
import logging
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from server.config import settings
from server.storage.db import db

logger = logging.getLogger(__name__)

_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def generate_embedding(text: str) -> List[float]:
    """Generate an embedding vector for the given text using OpenAI."""
    client = _get_client()
    response = await client.embeddings.create(
        input=text,
        model=settings.embedding_model,
    )
    return response.data[0].embedding


async def generate_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Generate embeddings for multiple texts in a single API call."""
    client = _get_client()
    response = await client.embeddings.create(
        input=texts,
        model=settings.embedding_model,
    )
    return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]


def generate_summary_for_live_session(
    session: Dict[str, Any],
    topics: List[Dict[str, Any]],
    message_stats: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate a text summary for a live-recorded session."""
    duration = (session.get("end_time") or 0) - session["start_time"]
    topic_parts = []
    for t in topics:
        freq_str = f", {t['avg_frequency']:.0f}Hz" if t.get("avg_frequency") else ""
        topic_parts.append(f"{t['topic']} ({t['message_count']} msgs{freq_str})")

    summary = (
        f"{duration:.1f}s live session with {len(topics)} topics: "
        + ", ".join(topic_parts)
        + "."
    )

    if message_stats:
        for topic_name, stats in message_stats.items():
            if stats.get("min") is not None and stats.get("max") is not None:
                summary += f" {topic_name} ranged [{stats['min']:.2f}, {stats['max']:.2f}]."

    return summary


def generate_summary_for_imported_session(
    session: Dict[str, Any],
    topics: List[Dict[str, Any]],
) -> str:
    """Generate a text summary for an imported LeRobot session."""
    duration = (session.get("end_time") or 0) - session["start_time"]
    ep_idx = session.get("episode_index", "?")
    dataset = session.get("dataset_name", "unknown")
    task = session.get("task", "unknown task")
    outcome = (session.get("outcome") or "unknown").upper()
    reward = session.get("total_reward")
    total_frames = session.get("total_frames", 0)
    fps = session.get("fps", 0)

    # Count motor dimensions from topics
    motor_count = 0
    for t in topics:
        if t["topic"] in ("/observation/state", "/action"):
            shape = t.get("shape")
            if shape and isinstance(shape, (list, str)):
                if isinstance(shape, str):
                    shape = json.loads(shape)
                if shape:
                    motor_count = max(motor_count, shape[0])

    summary = (
        f"{duration:.1f}s episode from {dataset} (episode {ep_idx}). "
        f"Task: {task}. "
    )

    if motor_count:
        summary += f"{motor_count} motors, "
    summary += f"{total_frames} frames at {fps:.0f}Hz. "
    summary += f"Outcome: {outcome}."

    if reward is not None:
        summary += f" Total reward: {reward:.1f}."

    return summary


async def generate_session_summary(session_id: str) -> Optional[str]:
    """Generate and store a text summary for a session."""
    session = await db.get_session(session_id)
    if not session:
        return None

    topics = await db.get_topics(session_id)
    source = session.get("source", "live")

    if source == "import":
        summary = generate_summary_for_imported_session(session, topics)
    else:
        summary = generate_summary_for_live_session(session, topics)

    await db.update_session(session_id, {"summary": summary})
    return summary


async def embed_session(session_id: str) -> Optional[List[float]]:
    """Generate and store an embedding for a session's summary."""
    session = await db.get_session(session_id)
    if not session:
        return None

    summary = session.get("summary")
    if not summary:
        summary = await generate_session_summary(session_id)
    if not summary:
        return None

    embedding = await generate_embedding(summary)
    await db.update_session(session_id, {"embedding": embedding})
    return embedding
