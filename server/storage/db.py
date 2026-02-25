import asyncio
from typing import Any, Dict, List, Optional

import duckdb

from server.config import settings

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id    VARCHAR PRIMARY KEY,
    source        VARCHAR NOT NULL,
    dataset_name  VARCHAR,
    episode_index INTEGER,
    task          VARCHAR,
    robot_type    VARCHAR,
    fps           DOUBLE,
    start_time    DOUBLE NOT NULL,
    end_time      DOUBLE,
    total_frames  INTEGER DEFAULT 0,
    status        VARCHAR NOT NULL,
    outcome       VARCHAR,
    total_reward  DOUBLE,
    features      JSON,
    summary       VARCHAR,
    embedding     FLOAT[1536],  -- must match settings.embedding_dim
    metrics_vec   JSON,
    umap_x        DOUBLE,
    umap_y        DOUBLE,
    created_at    TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    id            BIGINT,
    session_id    VARCHAR NOT NULL,
    timestamp     DOUBLE NOT NULL,
    topic         VARCHAR NOT NULL,
    data_type     VARCHAR NOT NULL,
    data          JSON,
    image_path    VARCHAR,
    frame_index   INTEGER
);

CREATE TABLE IF NOT EXISTS topics (
    session_id    VARCHAR NOT NULL,
    topic         VARCHAR NOT NULL,
    message_count INTEGER NOT NULL,
    first_time    DOUBLE NOT NULL,
    last_time     DOUBLE NOT NULL,
    avg_frequency DOUBLE,
    data_type     VARCHAR NOT NULL,
    shape         JSON,
    feature_names JSON,
    PRIMARY KEY (session_id, topic)
);
"""

INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_messages_seek ON messages (session_id, topic, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_messages_frame ON messages (session_id, frame_index)",
]


class Database:
    def __init__(self):
        self._conn: Optional[duckdb.DuckDBPyConnection] = None
        self._write_lock = asyncio.Lock()
        self._msg_counter = 0

    def connect(self):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(settings.db_path))
        self._conn.execute(SCHEMA_SQL)
        for idx_sql in INDEX_SQL:
            self._conn.execute(idx_sql)

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            raise RuntimeError("Database not connected")
        return self._conn

    async def read(self, query: str, params: Optional[list] = None) -> List[Dict[str, Any]]:
        def _exec():
            result = self.conn.execute(query, params or [])
            columns = [desc[0] for desc in result.description]
            return [dict(zip(columns, row)) for row in result.fetchall()]
        return await asyncio.to_thread(_exec)

    async def read_one(self, query: str, params: Optional[list] = None) -> Optional[Dict[str, Any]]:
        rows = await self.read(query, params)
        return rows[0] if rows else None

    async def write(self, query: str, params: Optional[list] = None):
        async with self._write_lock:
            await asyncio.to_thread(self.conn.execute, query, params or [])

    async def write_many(self, query: str, params_list: List[list]):
        async with self._write_lock:
            await asyncio.to_thread(self.conn.executemany, query, params_list)

    def next_msg_id(self) -> int:
        self._msg_counter += 1
        return self._msg_counter

    # --- Session helpers ---

    async def create_session(self, session: Dict[str, Any]):
        cols = ", ".join(session.keys())
        placeholders = ", ".join(["?"] * len(session))
        await self.write(
            f"INSERT INTO sessions ({cols}) VALUES ({placeholders})",
            list(session.values()),
        )

    async def update_session(self, session_id: str, updates: Dict[str, Any]):
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        await self.write(
            f"UPDATE sessions SET {set_clause} WHERE session_id = ?",
            list(updates.values()) + [session_id],
        )

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        return await self.read_one(
            "SELECT * FROM sessions WHERE session_id = ?", [session_id]
        )

    async def list_sessions(
        self, source: Optional[str] = None, limit: int = 100, offset: int = 0
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM sessions"
        params: list = []
        if source:
            query += " WHERE source = ?"
            params.append(source)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return await self.read(query, params)

    async def count_sessions(self, source: Optional[str] = None) -> int:
        query = "SELECT COUNT(*) as cnt FROM sessions"
        params: list = []
        if source:
            query += " WHERE source = ?"
            params.append(source)
        row = await self.read_one(query, params)
        return row["cnt"] if row else 0

    # --- Message helpers ---

    async def insert_messages(self, messages: List[list]):
        await self.write_many(
            "INSERT INTO messages (id, session_id, timestamp, topic, data_type, data, image_path, frame_index) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            messages,
        )

    async def seek_messages(
        self,
        session_id: str,
        start_time: float,
        end_time: float,
        topics: Optional[List[str]] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        query = (
            "SELECT * FROM messages "
            "WHERE session_id = ? AND timestamp >= ? AND timestamp <= ?"
        )
        params: list = [session_id, start_time, end_time]
        if topics:
            placeholders = ", ".join(["?"] * len(topics))
            query += f" AND topic IN ({placeholders})"
            params.extend(topics)
        query += " ORDER BY timestamp ASC LIMIT ?"
        params.append(limit)
        return await self.read(query, params)

    # --- Topic helpers ---

    async def compute_topic_summaries(self, session_id: str):
        await self.write(
            """
            INSERT OR REPLACE INTO topics (session_id, topic, message_count, first_time, last_time, avg_frequency, data_type, shape, feature_names)
            SELECT
                session_id,
                topic,
                COUNT(*) as message_count,
                MIN(timestamp) as first_time,
                MAX(timestamp) as last_time,
                CASE WHEN MAX(timestamp) > MIN(timestamp)
                    THEN COUNT(*) / (MAX(timestamp) - MIN(timestamp))
                    ELSE NULL END as avg_frequency,
                FIRST(data_type) as data_type,
                NULL as shape,
                NULL as feature_names
            FROM messages
            WHERE session_id = ?
            GROUP BY session_id, topic
            """,
            [session_id],
        )

    async def get_topics(self, session_id: str) -> List[Dict[str, Any]]:
        return await self.read(
            "SELECT * FROM topics WHERE session_id = ?", [session_id]
        )


db = Database()
