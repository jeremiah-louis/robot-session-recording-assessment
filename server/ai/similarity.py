import json
import logging
from typing import Any, Dict, List, Optional

import numpy as np

from server.config import settings
from server.storage.db import db

logger = logging.getLogger(__name__)


async def compute_metrics_vector(session_id: str) -> Optional[List[float]]:
    """Compute a numeric feature vector from telemetry stats for a session.

    The vector encodes: mean/std/min/max of each state/action dimension,
    duration, frame count, outcome (1=success, 0=failure, 0.5=unknown),
    and total reward.
    """
    session = await db.get_session(session_id)
    if not session:
        return None

    features: List[float] = []

    # Collect stats from numeric topics
    for topic_name in ("/observation/state", "/action"):
        rows = await db.read(
            "SELECT data FROM messages WHERE session_id = ? AND topic = ? AND data IS NOT NULL",
            [session_id, topic_name],
        )
        if rows:
            values = []
            for r in rows:
                d = r["data"]
                if isinstance(d, str):
                    d = json.loads(d)
                if isinstance(d, list):
                    values.append(d)
            if values:
                arr = np.array(values, dtype=np.float64)
                # Per-dimension: mean, std, min, max
                features.extend(arr.mean(axis=0).tolist())
                features.extend(arr.std(axis=0).tolist())
                features.extend(arr.min(axis=0).tolist())
                features.extend(arr.max(axis=0).tolist())
            else:
                features.extend([0.0] * 8)  # 2 dims * 4 stats
        else:
            features.extend([0.0] * 8)

    # Duration
    duration = (session.get("end_time") or 0) - session["start_time"]
    features.append(duration)

    # Frame count
    features.append(float(session.get("total_frames", 0)))

    # Outcome: 1=success, 0=failure, 0.5=unknown
    outcome = session.get("outcome")
    if outcome == "success":
        features.append(1.0)
    elif outcome == "failure":
        features.append(0.0)
    else:
        features.append(0.5)

    # Total reward (normalized later, raw for now)
    features.append(float(session.get("total_reward") or 0.0))

    await db.update_session(session_id, {"metrics_vec": json.dumps(features)})
    return features


async def compute_umap_projection(session_ids: Optional[List[str]] = None):
    """Compute UMAP 2D projection from embedding vectors and store coordinates.

    If session_ids is None, projects all sessions with embeddings.
    """
    try:
        import umap
    except ImportError:
        logger.error("umap-learn not installed, skipping UMAP projection")
        return

    if session_ids:
        placeholders = ", ".join(["?"] * len(session_ids))
        rows = await db.read(
            f"SELECT session_id, embedding FROM sessions WHERE embedding IS NOT NULL AND session_id IN ({placeholders})",
            session_ids,
        )
    else:
        rows = await db.read(
            "SELECT session_id, embedding FROM sessions WHERE embedding IS NOT NULL"
        )

    if len(rows) < 2:
        logger.info("Not enough sessions with embeddings for UMAP (need >= 2)")
        # If only one session, place it at origin
        for row in rows:
            await db.update_session(row["session_id"], {"umap_x": 0.0, "umap_y": 0.0})
        return

    ids = [r["session_id"] for r in rows]
    embeddings = np.array([r["embedding"] for r in rows], dtype=np.float32)

    n_neighbors = min(settings.umap_n_neighbors, len(ids) - 1)
    reducer = umap.UMAP(
        n_components=2,
        n_neighbors=n_neighbors,
        min_dist=settings.umap_min_dist,
        random_state=42,
    )
    coords = reducer.fit_transform(embeddings)

    for i, sid in enumerate(ids):
        await db.update_session(sid, {
            "umap_x": float(coords[i, 0]),
            "umap_y": float(coords[i, 1]),
        })

    logger.info(f"UMAP projection computed for {len(ids)} sessions")


async def get_similarity_graph() -> Dict[str, Any]:
    """Build the similarity graph data structure for the frontend.

    Returns nodes (sessions with UMAP coords) and edges (above threshold similarity).
    """
    rows = await db.read(
        """
        SELECT session_id, dataset_name, episode_index, outcome, total_reward,
               umap_x, umap_y, summary, source, metrics_vec
        FROM sessions
        WHERE umap_x IS NOT NULL AND umap_y IS NOT NULL
        """
    )

    if not rows:
        return {"nodes": [], "edges": []}

    # Build nodes
    nodes = []
    for r in rows:
        ep = r.get("episode_index")
        label = f"Episode {ep}" if ep is not None else r["session_id"][:8]
        nodes.append({
            "id": r["session_id"],
            "label": label,
            "outcome": r.get("outcome"),
            "reward": r.get("total_reward"),
            "x": r["umap_x"],
            "y": r["umap_y"],
        })

    # Build edges from metrics_vec cosine similarity
    edges = []
    vecs = {}
    for r in rows:
        mv = r.get("metrics_vec")
        if mv:
            if isinstance(mv, str):
                mv = json.loads(mv)
            vecs[r["session_id"]] = np.array(mv, dtype=np.float64)

    sids = list(vecs.keys())
    for i in range(len(sids)):
        for j in range(i + 1, len(sids)):
            a, b = vecs[sids[i]], vecs[sids[j]]
            norm_a, norm_b = np.linalg.norm(a), np.linalg.norm(b)
            if norm_a > 0 and norm_b > 0:
                sim = float(np.dot(a, b) / (norm_a * norm_b))
                if sim >= settings.similarity_threshold:
                    edges.append({
                        "source": sids[i],
                        "target": sids[j],
                        "weight": round(sim, 4),
                    })

    return {"nodes": nodes, "edges": edges}
