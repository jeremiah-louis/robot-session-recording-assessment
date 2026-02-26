# Robot Session Recording & Intelligence Pipeline

Record, replay, and query robot telemetry with AI-powered search and visual similarity analysis.

## What It Does

Captures multimodal robot sensor data (joint states, gripper feedback, camera frames) in real-time, stores it efficiently, and lets you search and explore episodes using natural language and intelligent similarity matching. Built to ingest both live streams and LeRobot datasets.

## Quick Start

```bash
# Start the server
docker-compose up

# In another terminal, run the frontend
cd frontend && npm install && npm run dev

# In another terminal, stream mock robot data
python -m client.mock_robot

# Open http://localhost:5173 to explore sessions
```

Or run the frontend and server separately for development:

```bash
# Backend
pip install -r requirements.txt
uvicorn server.main:app --host 0.0.0.0 --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

## CLI Scripts

### `client/mock_robot.py` — Stream live mock telemetry

Simulates a 6-DOF robot streaming joint states, gripper feedback, and camera frames over WebSocket.

```bash
python -m client.mock_robot [flags]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--server-url` | `ws://localhost:8000/ws/ingest` | WebSocket endpoint to connect to |
| `--duration` | `60.0` | How long to stream in seconds |
| `--session-id` | auto-generated | Session ID to use (e.g. `live-abc123`); random if omitted |

Examples:

```bash
# 30-second stream with a custom session ID
python -m client.mock_robot --duration 30 --session-id test-run-01

# Point at a non-default server
python -m client.mock_robot --server-url ws://192.168.1.10:8000/ws/ingest
```

---

### `scripts/import_lerobot.py` — Import a LeRobot dataset

Downloads a dataset from Hugging Face, extracts telemetry + video frames, and inserts them as sessions into DuckDB. One session per episode.

```bash
python scripts/import_lerobot.py [flags]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--dataset` | `lerobot/pusht` | Hugging Face dataset repo ID |
| `--episodes` | `50` | Maximum number of episodes to import |
| `--skip-download` | off | Reuse a previously cached download instead of re-fetching |
| `--embed` | off | After import, generate AI summaries, embeddings, metrics vectors, and UMAP coords in one pass |

Examples:

```bash
# Import 100 episodes of pusht
python scripts/import_lerobot.py --dataset lerobot/pusht --episodes 100

# Re-import from cache and generate AI features immediately
python scripts/import_lerobot.py --skip-download --embed

# Import a different dataset
python scripts/import_lerobot.py --dataset lerobot/aloha_sim_insertion_human --episodes 25
```

---

### `scripts/seed_embeddings.py` — Backfill AI features

Generates summaries, OpenAI embeddings, metrics vectors, and UMAP coordinates for every session already in the database. Useful after a bulk import without `--embed`, or to refresh stale data.

```bash
python -m scripts.seed_embeddings [flags]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--batch-size` | `50` | Number of sessions to embed per OpenAI API call |

Examples:

```bash
# Seed with default batch size
python -m scripts.seed_embeddings

# Use smaller batches to stay under rate limits
python -m scripts.seed_embeddings --batch-size 20
```

---

## Key Features

- **Live Ingestion**: WebSocket endpoint streams telemetry with backpressure handling
- **Fast Playback**: Sub-200ms time-range queries on large sessions via DuckDB columnar storage
- **AI Search**: Find episodes with natural language ("successful episodes with high reward")
- **Similarity Graph**: Interactive 2D visualization of all episodes with smart clustering
- **LeRobot Integration**: Import pre-recorded datasets alongside live data
- **Export**: Download session telemetry as JSON

## Project Layout

```
server/          → FastAPI backend (ingestion, storage, API)
client/          → Mock robot client for testing
scripts/         → Dataset import and embedding generation
frontend/        → React UI (session explorer, similarity graph)
data/            → DuckDB database + image frames (created at runtime)
```

## Core API Routes

- `GET /sessions` — List all sessions
- `GET /sessions/{id}` — Session metadata + AI summary
- `POST /sessions/{id}/seek` — Query messages by time range (JSON: `{"start_time": 5, "end_time": 10}`)
- `POST /sessions/search` — NL search over sessions (JSON: `{"query": "pick and place"}`)
- `GET /sessions/similarity-graph` — Full graph for visualization

## Tech Stack

- **Server**: Python + FastAPI (async, WebSocket support)
- **Storage**: DuckDB (columnar, time-range optimized) + filesystem for images
- **AI**: OpenAI embeddings for semantic search
- **Frontend**: React + shadcn components (Vite, Tailwind)
- **Import**: LeRobot datasets via Hugging Face

## Performance

I did a test against 206 imported episodes from `lerobot/pusht` (~25,000+ messages, 15MB DuckDB, 100MB image store). All times are a median over 20 runs.

### Query Latency


| Endpoint                    | What                              | Median     | p95    |
| --------------------------- | --------------------------------- | ---------- | ------ |
| `POST /seek` (full range)   | 738 messages across 24.5s session | **6.1ms**  | 6.4ms  |
| `POST /seek` (2s window)    | 63 messages in a narrow slice     | **2.5ms**  | 2.7ms  |
| `POST /seek` (single topic) | 246 messages, one topic filtered  | **3.5ms**  | 3.6ms  |
| `GET /sessions`             | List 100 sessions with metadata   | **18.5ms** | 33.3ms |
| `GET /sessions/{id}`        | Single session detail             | **1.2ms**  | 1.3ms  |
| `GET /export`               | Full session JSON download        | **6.7ms**  | 7.3ms  |


All seek queries well under the 200ms target — DuckDB's columnar engine + composite index on `(session_id, topic, timestamp)` does the heavy lifting.

### AI Features


| Endpoint                | What                                                      | Median    | p95   |
| ----------------------- | --------------------------------------------------------- | --------- | ----- |
| `POST /search`          | NL query → embed → cosine similarity over 206 sessions    | **616ms** | 4.5s  |
| `GET /similarity-graph` | UMAP projection + edge computation (206 nodes, 21K edges) | **130ms** | 153ms |


NL search latency is dominated by the OpenAI embedding API call (~500ms). The local similarity computation is near-instant. The similarity graph is fully server-side — no external API dependency.

### Ingestion

LeRobot import reads Parquet natively (zero conversion overhead) and batch-inserts into DuckDB. 206 episodes with video frame extraction imported in a single pass. Live WebSocket ingestion uses bounded async queues with backpressure signaling.

## Configuration

Set `OPENAI_API_KEY` in your environment to enable AI features:

```bash
export OPENAI_API_KEY=sk-...
docker-compose up
```

---

**See WRITEUP.pdf for architecture details and design tradeoffs.**