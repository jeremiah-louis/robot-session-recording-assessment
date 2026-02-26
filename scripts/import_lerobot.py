"""Import LeRobot dataset episodes into the recording system.

Downloads a LeRobot-format dataset from HuggingFace Hub, reads the parquet
telemetry data and (optionally) extracts video frames, then inserts everything
into our DuckDB storage as individual sessions — one session per episode.

Usage:
    python scripts/import_lerobot.py --dataset lerobot/pusht --episodes 50
    python scripts/import_lerobot.py --skip-download  # reuse cached download
"""

import argparse
import io
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import av
import pyarrow.parquet as pq
from huggingface_hub import snapshot_download

# Add project root to path so we can import server modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.config import settings
from server.storage.db import db
from server.storage.image_store import image_store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Shared SQL for inserting message rows (telemetry + images use the same schema)
INSERT_MESSAGE_SQL = (
    "INSERT INTO messages (id, session_id, timestamp, topic, data_type, data, image_path, frame_index) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def to_list(value) -> list:
    """Convert an array-like value (numpy array, tensor, etc.) to a plain Python list."""
    if hasattr(value, "tolist"):
        return value.tolist()
    return list(value)


def get_frame_index(episode_data: dict, row_index: int) -> int:
    """Return the frame_index for a given row, falling back to row_index if unavailable."""
    if "frame_index" in episode_data and row_index < len(episode_data["frame_index"]):
        return int(episode_data["frame_index"][row_index])
    return row_index


def download_dataset(dataset_name: str) -> Path:
    """Download dataset from HuggingFace Hub via snapshot_download. Returns local path."""
    logger.info("Downloading %s...", dataset_name)
    local_dir = snapshot_download(
        repo_id=dataset_name,
        repo_type="dataset",
        local_dir=settings.data_dir / "hf_cache" / dataset_name.replace("/", "_"),
    )
    return Path(local_dir)


def load_info(dataset_dir: Path) -> dict:
    """Load dataset metadata from meta/info.json (contains fps, features, episode count, etc.)."""
    with open(dataset_dir / "meta" / "info.json") as f:
        return json.load(f)


def load_tasks(dataset_dir: Path) -> Dict[int, str]:
    """Load task descriptions from meta/tasks.parquet. Returns {task_index: description}."""
    tasks_path = dataset_dir / "meta" / "tasks.parquet"
    if not tasks_path.exists():
        return {}
    table = pq.read_table(tasks_path)
    df = table.to_pydict()
    # I noticed that the task description column name varies by dataset version:
    # v3.0 (the version we are currently using) uses '__index_level_0__', newer versions use 'task'
    task_col = "task" if "task" in df else "__index_level_0__"
    return dict(zip(df["task_index"], df[task_col]))


def extract_video_frames(video_path: Path, num_frames: int) -> list:
    """Decode up to num_frames from an MP4 video file. Returns list of PIL Images."""
    frames = []
    container = av.open(str(video_path))
    try:
        stream = container.streams.video[0]
        for frame in container.decode(stream):
            frames.append(frame.to_image())
            if len(frames) >= num_frames:
                break
    finally:
        container.close()
    return frames


def resolve_video_path(dataset_dir: Path, info: dict, episode_index: int) -> Optional[Path]:
    """Resolve the video file path for an episode.

    LeRobot v3.0 organizes videos as:
        videos/{video_key}/chunk-{chunk}/file-{file}.mp4
    We try the direct path first, then fall back to the template in info.json.
    """
    chunks_size = info.get("chunks_size", 1000)

    # Divide the episode index by the chunks size and round to nearest integer to get the chunk index
    chunk_index = episode_index // chunks_size

    # Try direct path: videos/observation.image/chunk-000/file-000.mp4
    video_path = dataset_dir / f"videos/observation.image/chunk-{chunk_index:03d}/file-{episode_index:03d}.mp4"
    if video_path.exists():
        return video_path

    # Fall back to the template pattern from info.json
    video_template = info.get("video_path", "")
    if video_template:
        file_index = episode_index % chunks_size
        video_path = dataset_dir / video_template.format(
            video_key="observation.image",
            chunk_index=chunk_index,
            file_index=file_index,
        )
        if video_path.exists():
            return video_path

    return None


def determine_outcome(episode_data: dict) -> Optional[str]:
    """Check if any frame in the episode has next.success=True."""
    if "next.success" not in episode_data:
        return None
    return "success" if any(episode_data["next.success"]) else "failure"


def determine_total_reward(episode_data: dict) -> Optional[float]:
    """Sum all next.reward values across the episode."""
    if "next.reward" not in episode_data:
        return None
    return float(sum(episode_data["next.reward"]))


def determine_task(episode_data: dict, tasks: Dict[int, str]) -> Optional[str]:
    """Look up the task description for this episode's task_index."""
    if "task_index" not in episode_data:
        return None
    task_indices = episode_data["task_index"]
    return tasks.get(task_indices[0]) if task_indices else None


def build_telemetry_rows(
    episode_data: dict, session_id: str, timestamps: list, start_msg_id: int,
) -> Tuple[List[list], int]:
    """Build message rows for observation.state and action topics.

    Maps LeRobot features to our topic schema:
        observation.state -> /observation/state (float32[])
        action            -> /action            (float32[])

    Returns (rows, next_available_msg_id).
    """
    rows = []
    msg_id = start_msg_id

    for i, ts in enumerate(timestamps):
        ts = float(ts)
        frame_idx = get_frame_index(episode_data, i)

        # Robot state observation (e.g. motor positions)
        if "observation.state" in episode_data:
            state_list = to_list(episode_data["observation.state"][i])
            rows.append([msg_id, session_id, ts, "/observation/state", "float32[]",
                         json.dumps(state_list), None, frame_idx])
            msg_id += 1

        # Robot action commands
        if "action" in episode_data:
            action_list = to_list(episode_data["action"][i])
            rows.append([msg_id, session_id, ts, "/action", "float32[]",
                         json.dumps(action_list), None, frame_idx])
            msg_id += 1

    return rows, msg_id


def build_image_rows(
    frames: list, episode_data: dict, session_id: str,
    timestamps: list, fps: float, start_msg_id: int,
) -> Tuple[List[list], int]:
    """Encode decoded video frames as JPEG and store them on disk.

    Each frame is saved via image_store and referenced by path in the message row.
    Falls back to computed timestamps (frame_index / fps) if we have more frames
    than timestamp entries.

    Returns (rows, next_available_msg_id).
    """
    rows = []
    msg_id = start_msg_id

    for i, img in enumerate(frames):
        # Use parquet timestamp if available, otherwise compute from frame rate
        ts = float(timestamps[i]) if i < len(timestamps) else float(i) / fps
        frame_idx = get_frame_index(episode_data, i)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        img_path = image_store.save(session_id, "/observation/image", ts, buf.getvalue())

        rows.append([msg_id, session_id, ts, "/observation/image", "image_ref",
                     None, img_path, frame_idx])
        msg_id += 1

    return rows, msg_id


# ---------------------------------------------------------------------------
# Core import logic
# ---------------------------------------------------------------------------

def import_episode(
    dataset_dir: Path, info: dict, tasks: Dict[int, str],
    episode_data: dict, episode_index: int, dataset_name: str,
) -> None:
    """Import a single episode into the database.

    Creates a session record, inserts telemetry messages (state + action),
    extracts video frames if the MP4 exists, and computes topic summaries.
    """
    session_id = f"import-{dataset_name.replace('/', '_')}-ep{episode_index:04d}"

    # Skip if already imported
    existing = db.conn.execute(
        "SELECT 1 FROM sessions WHERE session_id = ?", [session_id]
    ).fetchone()
    if existing:
        logger.info("  Skipping episode %d (already imported)", episode_index)
        return

    fps = info["fps"]
    timestamps = episode_data["timestamp"]
    num_frames = len(timestamps)

    db.conn.execute(
        """INSERT INTO sessions (session_id, source, dataset_name, episode_index, task,
           robot_type, fps, start_time, end_time, total_frames, status, outcome,
           total_reward, features)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            session_id, "import", dataset_name, episode_index,
            determine_task(episode_data, tasks),
            info.get("robot_type", "unknown"), fps,
            float(timestamps[0]), float(timestamps[-1]),
            num_frames, "completed",
            determine_outcome(episode_data),
            determine_total_reward(episode_data),
            json.dumps(info.get("features", {})),
        ],
    )

    # Insert state and action telemetry as message rows
    msg_id = db.next_msg_id()
    telemetry_rows, msg_id = build_telemetry_rows(episode_data, session_id, timestamps, msg_id)
    if telemetry_rows:
        db.conn.executemany(INSERT_MESSAGE_SQL, telemetry_rows)

    # Extract video frames (observation.image) and store as JPEG files
    video_path = resolve_video_path(dataset_dir, info, episode_index)
    image_rows = []

    if video_path is not None:
        logger.info("  Extracting video frames from %s", video_path.name)
        frames = extract_video_frames(video_path, num_frames)
        image_rows, msg_id = build_image_rows(
            frames, episode_data, session_id, timestamps, fps, msg_id,
        )
        if image_rows:
            db.conn.executemany(INSERT_MESSAGE_SQL, image_rows)
    else:
        logger.warning("  Video not found for episode %d, skipping image extraction", episode_index)

    # Precompute per-topic stats (message count, frequency, time range)
    db.conn.execute(
        """
        INSERT OR REPLACE INTO topics (session_id, topic, message_count, first_time, last_time, avg_frequency, data_type, shape, feature_names)
        SELECT
            session_id, topic, COUNT(*) as message_count,
            MIN(timestamp) as first_time, MAX(timestamp) as last_time,
            CASE WHEN MAX(timestamp) > MIN(timestamp)
                THEN COUNT(*) / (MAX(timestamp) - MIN(timestamp))
                ELSE NULL END as avg_frequency,
            FIRST(data_type) as data_type, NULL as shape, NULL as feature_names
        FROM messages WHERE session_id = ?
        GROUP BY session_id, topic
        """,
        [session_id],
    )

    total_messages = len(telemetry_rows) + len(image_rows)
    logger.info("  Imported episode %d: %d frames, %d messages", episode_index, num_frames, total_messages)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Import LeRobot dataset")
    parser.add_argument("--dataset", default="lerobot/pusht", help="HuggingFace dataset name")
    parser.add_argument("--episodes", type=int, default=50, help="Number of episodes to import")
    parser.add_argument("--skip-download", action="store_true", help="Skip download if already cached")
    parser.add_argument("--embed", action="store_true", help="Generate AI summaries, embeddings, and metrics after import")
    args = parser.parse_args()

    # Use cached download if available and --skip-download is set
    cache_dir = settings.data_dir / "hf_cache" / args.dataset.replace("/", "_")
    if args.skip_download and cache_dir.exists():
        dataset_dir = cache_dir
        logger.info("Using cached dataset at %s", dataset_dir)
    else:
        dataset_dir = download_dataset(args.dataset)

    # Load dataset metadata and task descriptions
    info = load_info(dataset_dir)
    tasks = load_tasks(dataset_dir)
    total_episodes = info["total_episodes"]
    num_to_import = min(args.episodes, total_episodes)

    logger.info("Dataset: %s (%d total episodes, importing %d)", args.dataset, total_episodes, num_to_import)
    logger.info("FPS: %d, Features: %s", info["fps"], list(info.get("features", {}).keys()))

    db.connect()

    # All 206 pusht episodes live in a single parquet file
    parquet_path = dataset_dir / "data" / "chunk-000" / "file-000.parquet"
    if not parquet_path.exists():
        logger.error("Parquet file not found: %s", parquet_path)
        return

    logger.info("Reading parquet: %s", parquet_path)
    table = pq.read_table(parquet_path)
    df = table.to_pydict()

    # Group rows by episode_index and import each episode as a separate session
    episode_indices = df["episode_index"]
    unique_episodes = sorted(set(episode_indices))[:num_to_import]

    for ep_idx in unique_episodes:
        # Build per-episode dict by filtering rows matching this episode
        mask = [i for i, idx in enumerate(episode_indices) if idx == ep_idx]
        episode_data = {col: [df[col][i] for i in mask] for col in df}
        import_episode(dataset_dir, info, tasks, episode_data, ep_idx, args.dataset)

    def make_session_id(ep_idx: int) -> str:
        return f"import-{args.dataset.replace('/', '_')}-ep{ep_idx:04d}"

    if args.embed:
        logger.info("Generating AI features (summaries, embeddings, metrics)...")
        import asyncio
        from server.ai.embeddings import embed_session
        from server.ai.similarity import compute_metrics_vector, compute_umap_projection

        async def _embed_all():
            for ep_idx in unique_episodes:
                sid = make_session_id(ep_idx)
                try:
                    await embed_session(sid)
                    await compute_metrics_vector(sid)
                except Exception:
                    logger.warning("Failed to embed session %s", sid, exc_info=True)
            await compute_umap_projection([make_session_id(idx) for idx in unique_episodes])

        asyncio.run(_embed_all())
        logger.info("AI features generated")

    db.close()
    logger.info("Import complete: %d episodes imported", len(unique_episodes))


if __name__ == "__main__":
    main()
