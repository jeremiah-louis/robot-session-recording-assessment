"""
Tests validating 6 security and correctness fixes.

Each test is isolated and does not touch the real data directory.

Design notes:
- Python 3.9 destroys the event loop after asyncio.run(), so every call that
  needs a running loop must create its own via asyncio.new_event_loop().
- Database() calls asyncio.Lock() at construction time, which in Python 3.9
  requires an active event loop.  We therefore construct Database instances
  *inside* the coroutine that the event loop runs, or we create the event loop
  first and then construct the Database.
"""

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb
import numpy as np
import pytest

# Ensure the project root is on sys.path so server.* imports work.
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Utility: run a coroutine on a fresh event loop without creating a Database
# outside of an active loop.
# ---------------------------------------------------------------------------

def run(coro):
    """Run a coroutine on a brand-new event loop (safe for Python 3.9)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def make_db_conn(db_file: Path):
    """
    Open a DuckDB connection and run the schema SQL.
    Returns a raw duckdb.DuckDBPyConnection (not the Database wrapper) so
    callers can build a Database inside a running event loop.
    """
    from server.storage.db import SCHEMA_SQL, INDEX_SQL
    conn = duckdb.connect(str(db_file))
    conn.execute(SCHEMA_SQL)
    for idx_sql in INDEX_SQL:
        conn.execute(idx_sql)
    return conn


def build_database_on_conn(conn: duckdb.DuckDBPyConnection):
    """
    Build a server.storage.db.Database that wraps an already-open connection.
    Must be called while an event loop is running (asyncio.Lock() requirement).
    """
    from server.storage.db import Database
    db_instance = Database()
    db_instance._conn = conn
    return db_instance


# ============================================================
# Fix 1 – SQL injection via invalid column names
# ============================================================

class TestSQLInjectionFix:
    """
    server/storage/db.py: create_session / update_session validate column
    names against _SESSION_COLUMNS allowlist and raise ValueError for
    anything outside that set.
    """

    def test_create_session_rejects_invalid_column(self, tmp_path):
        """Passing a column name not in _SESSION_COLUMNS must raise ValueError."""
        db_file = tmp_path / "test.duckdb"

        async def _run():
            conn = make_db_conn(db_file)
            db_instance = build_database_on_conn(conn)
            evil = {"DROP TABLE sessions; --": "value", "session_id": "s1"}
            with pytest.raises(ValueError, match="Invalid column names"):
                await db_instance.create_session(evil)

        run(_run())

    def test_create_session_accepts_valid_columns(self, tmp_path):
        """A dict with only known column names must not raise."""
        db_file = tmp_path / "test.duckdb"

        async def _run():
            conn = make_db_conn(db_file)
            db_instance = build_database_on_conn(conn)
            valid = {
                "session_id": "valid-session-1",
                "source": "live",
                "start_time": 0.0,
                "status": "active",
            }
            await db_instance.create_session(valid)  # should not raise

        run(_run())

    def test_update_session_rejects_invalid_column(self, tmp_path):
        """update_session must also reject invalid column names."""
        db_file = tmp_path / "test.duckdb"

        async def _run():
            conn = make_db_conn(db_file)
            db_instance = build_database_on_conn(conn)
            with pytest.raises(ValueError, match="Invalid column names"):
                await db_instance.update_session(
                    "some-session",
                    {"evil_col'; DROP TABLE sessions; --": "x"},
                )

        run(_run())

    def test_update_session_accepts_valid_columns(self, tmp_path):
        """update_session with known column names must succeed."""
        db_file = tmp_path / "test.duckdb"

        async def _run():
            conn = make_db_conn(db_file)
            db_instance = build_database_on_conn(conn)
            await db_instance.create_session({
                "session_id": "valid-session-2",
                "source": "live",
                "start_time": 0.0,
                "status": "active",
            })
            await db_instance.update_session(
                "valid-session-2", {"status": "complete"}
            )

        run(_run())

    def test_session_columns_allowlist_is_frozen(self):
        """_SESSION_COLUMNS must be a frozenset (immutable) to prevent bypass."""
        from server.storage.db import Database
        assert isinstance(Database._SESSION_COLUMNS, frozenset)

    def test_validate_columns_helper_raises_for_empty_string(self, tmp_path):
        """An empty string is also not a valid column name."""
        db_file = tmp_path / "test.duckdb"

        async def _run():
            conn = make_db_conn(db_file)
            db_instance = build_database_on_conn(conn)
            with pytest.raises(ValueError):
                await db_instance.create_session({"": "value", "session_id": "s"})

        run(_run())


# ============================================================
# Fix 2 – Path traversal in ImageStore
# ============================================================

class TestPathTraversalFix:
    """
    server/storage/image_store.py: load() and exists() call _validate_path()
    which rejects any resolved path outside base_dir.
    """

    def _make_store(self, tmp_path: Path):
        from server.storage.image_store import ImageStore
        base = tmp_path / "images"
        base.mkdir()
        return ImageStore(base_dir=base)

    def test_load_rejects_path_traversal(self, tmp_path):
        store = self._make_store(tmp_path)
        traversal = str(tmp_path / "images" / ".." / ".." / "etc" / "passwd")
        with pytest.raises(ValueError, match="outside the image store directory"):
            store.load(traversal)

    def test_exists_rejects_path_traversal(self, tmp_path):
        store = self._make_store(tmp_path)
        traversal = str(tmp_path / "images" / ".." / ".." / "etc" / "passwd")
        with pytest.raises(ValueError, match="outside the image store directory"):
            store.exists(traversal)

    def test_load_rejects_absolute_outside_base(self, tmp_path):
        store = self._make_store(tmp_path)
        with pytest.raises(ValueError, match="outside the image store directory"):
            store.load("/etc/passwd")

    def test_load_accepts_path_inside_base(self, tmp_path):
        store = self._make_store(tmp_path)
        valid_file = tmp_path / "images" / "test.jpg"
        valid_file.write_bytes(b"fake-jpeg")
        result = store.load(str(valid_file))
        assert result == b"fake-jpeg"

    def test_exists_accepts_path_inside_base(self, tmp_path):
        store = self._make_store(tmp_path)
        valid_file = tmp_path / "images" / "test2.jpg"
        valid_file.write_bytes(b"x")
        assert store.exists(str(valid_file)) is True

    def test_exists_returns_false_for_missing_path_inside_base(self, tmp_path):
        store = self._make_store(tmp_path)
        missing = str(tmp_path / "images" / "missing.jpg")
        assert store.exists(missing) is False


# ============================================================
# Fix 3 – Data serialisation: json.dumps instead of str()
# ============================================================

class TestDataSerializationFix:
    """
    server/ingestion/buffer.py: _msg_to_row() uses json.dumps(data) so the
    stored value is valid JSON, not Python repr (single quotes, True/False, etc.)
    """

    def _call_msg_to_row(self, tmp_path: Path, msg: dict):
        """Helper: run _msg_to_row inside a live event loop with a real DB."""
        db_file = tmp_path / "buf_test.duckdb"

        async def _run():
            from server.storage.image_store import ImageStore
            from server.ingestion.buffer import SessionBuffer
            import server.ingestion.buffer as buf_mod

            conn = make_db_conn(db_file)
            db_instance = build_database_on_conn(conn)

            base = tmp_path / "images"
            base.mkdir(exist_ok=True)
            store = ImageStore(base_dir=base)

            # Patch module-level singletons
            original_db = buf_mod.db
            original_store = buf_mod.image_store
            buf_mod.db = db_instance
            buf_mod.image_store = store
            try:
                buf = SessionBuffer(session_id="test-session")
                return buf._msg_to_row(msg)
            finally:
                buf_mod.db = original_db
                buf_mod.image_store = original_store

        return run(_run())

    def test_dict_data_produces_valid_json(self, tmp_path):
        msg = {
            "data": {"joints": [1.0, 2.0, 3.0], "flag": True},
            "data_type": "joint_state",
            "timestamp": 1.0,
            "topic": "/joint_states",
        }
        row = self._call_msg_to_row(tmp_path, msg)
        assert row is not None
        # Index 5 is the data column
        data_str = row[5]
        assert data_str is not None
        # Must be parseable by json.loads (raises if Python repr was stored)
        parsed = json.loads(data_str)
        assert parsed == {"joints": [1.0, 2.0, 3.0], "flag": True}

    def test_dict_data_uses_double_quotes(self, tmp_path):
        """Python repr produces single quotes; JSON must use double quotes."""
        msg = {
            "data": {"key": "value"},
            "data_type": "joint_state",
            "timestamp": 2.0,
            "topic": "/test",
        }
        row = self._call_msg_to_row(tmp_path, msg)
        data_str = row[5]
        assert '"key"' in data_str
        assert '"value"' in data_str

    def test_bool_serialised_as_lowercase_json(self, tmp_path):
        """json.dumps serialises True as 'true'; str() would give 'True'."""
        msg = {
            "data": {"ok": True},
            "data_type": "status",
            "timestamp": 3.0,
            "topic": "/status",
        }
        row = self._call_msg_to_row(tmp_path, msg)
        data_str = row[5]
        assert "true" in data_str
        assert "True" not in data_str

    def test_none_data_stored_as_python_none(self, tmp_path):
        """If data is None the column should be Python None, not the string 'null'."""
        msg = {
            "data": None,
            "data_type": "marker",
            "timestamp": 4.0,
            "topic": "/marker",
        }
        row = self._call_msg_to_row(tmp_path, msg)
        # data column (index 5) should be Python None
        assert row[5] is None


# ============================================================
# Fix 4 – Message ID sequence (DuckDB sequence + persist)
# ============================================================

class TestMessageIdSequence:
    """
    server/storage/db.py: next_msg_id() uses DuckDB's msg_id_seq sequence.
    IDs must be monotonically increasing and must persist across a reconnect.
    """

    def test_next_msg_id_increments(self, tmp_path):
        db_file = tmp_path / "seq_test.duckdb"
        conn = make_db_conn(db_file)

        async def _run():
            db_instance = build_database_on_conn(conn)
            id1 = db_instance.next_msg_id()
            id2 = db_instance.next_msg_id()
            assert id2 > id1, f"Expected id2 ({id2}) > id1 ({id1})"

        run(_run())

    def test_next_msg_id_strictly_sequential(self, tmp_path):
        db_file = tmp_path / "seq_test2.duckdb"
        conn = make_db_conn(db_file)

        async def _run():
            db_instance = build_database_on_conn(conn)
            ids = [db_instance.next_msg_id() for _ in range(5)]
            for a, b in zip(ids, ids[1:]):
                assert b > a, f"IDs not strictly increasing: {ids}"

        run(_run())

    def test_msg_id_persists_across_reconnect(self, tmp_path):
        """The sequence value must survive close + re-open of the same DB file."""
        db_file = tmp_path / "seq_persist.duckdb"

        async def _first_connection():
            conn = make_db_conn(db_file)
            db_instance = build_database_on_conn(conn)
            ids = [db_instance.next_msg_id() for _ in range(3)]
            db_instance.close()
            return ids[-1]  # last ID before close

        async def _second_connection():
            conn = make_db_conn(db_file)
            db_instance = build_database_on_conn(conn)
            first_id = db_instance.next_msg_id()
            db_instance.close()
            return first_id

        last_before = run(_first_connection())
        first_after = run(_second_connection())

        assert first_after > last_before, (
            f"After reconnect, next_msg_id() ({first_after}) should be "
            f"greater than last value before close ({last_before})"
        )

    def test_next_msg_id_returns_integer(self, tmp_path):
        db_file = tmp_path / "seq_type.duckdb"
        conn = make_db_conn(db_file)

        async def _run():
            db_instance = build_database_on_conn(conn)
            msg_id = db_instance.next_msg_id()
            assert isinstance(msg_id, int), f"Expected int, got {type(msg_id)}"

        run(_run())


# ============================================================
# Fix 5 – Vectorised similarity computation
# ============================================================

class TestVectorizedSimilarity:
    """
    server/ai/similarity.py: get_similarity_graph() uses matrix multiplication
    for cosine similarity instead of a per-pair loop.  Tests verify correct
    edge weights and threshold filtering.
    """

    @staticmethod
    def _cosine(a, b):
        a = np.array(a, dtype=np.float64)
        b = np.array(b, dtype=np.float64)
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na == 0 or nb == 0:
            return 0.0
        return float(np.dot(a, b) / (na * nb))

    def _build_db_with_sessions(self, tmp_path: Path, sessions_data: List[Dict]):
        """
        Populate a temp DB file directly via a raw DuckDB connection (no
        Database wrapper needed here – schema SQL is executed by make_db_conn).
        """
        db_file = tmp_path / "sim_test.duckdb"
        conn = make_db_conn(db_file)
        for s in sessions_data:
            conn.execute(
                """
                INSERT INTO sessions
                  (session_id, source, start_time, status, umap_x, umap_y, metrics_vec)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    s["session_id"],
                    "import",
                    0.0,
                    "complete",
                    s["umap_x"],
                    s["umap_y"],
                    json.dumps(s["metrics_vec"]),
                ],
            )
        return db_file, conn

    def _run_get_similarity_graph(self, db_file: Path, conn, threshold: float = 0.7):
        """
        Wire up server.ai.similarity to use our temp DB, then call
        get_similarity_graph() and return its result.
        """
        import server.ai.similarity as sim_mod
        import server.storage.db as db_mod

        async def _run():
            db_instance = build_database_on_conn(conn)
            original_sim_db = sim_mod.db
            original_db_mod = db_mod.db
            original_threshold = sim_mod.settings.similarity_threshold
            sim_mod.db = db_instance
            db_mod.db = db_instance
            sim_mod.settings.similarity_threshold = threshold
            try:
                return await sim_mod.get_similarity_graph()
            finally:
                sim_mod.db = original_sim_db
                db_mod.db = original_db_mod
                sim_mod.settings.similarity_threshold = original_threshold

        return run(_run())

    def test_identical_vectors_similarity_is_one(self, tmp_path):
        """Two identical non-zero vectors must produce a cosine similarity of 1.0."""
        vec = [1.0, 2.0, 3.0, 4.0]
        db_file, conn = self._build_db_with_sessions(tmp_path, [
            {"session_id": "s1", "umap_x": 0.0, "umap_y": 0.0, "metrics_vec": vec},
            {"session_id": "s2", "umap_x": 1.0, "umap_y": 1.0, "metrics_vec": vec},
        ])
        result = self._run_get_similarity_graph(db_file, conn, threshold=0.7)
        assert len(result["nodes"]) == 2
        assert len(result["edges"]) == 1
        assert abs(result["edges"][0]["weight"] - 1.0) < 1e-4

    def test_orthogonal_vectors_no_edge(self, tmp_path):
        """Orthogonal vectors have cosine similarity 0.0 – no edge should appear."""
        db_file, conn = self._build_db_with_sessions(tmp_path, [
            {"session_id": "s1", "umap_x": 0.0, "umap_y": 0.0, "metrics_vec": [1.0, 0.0]},
            {"session_id": "s2", "umap_x": 1.0, "umap_y": 1.0, "metrics_vec": [0.0, 1.0]},
        ])
        result = self._run_get_similarity_graph(db_file, conn, threshold=0.7)
        assert len(result["edges"]) == 0

    def test_edge_weights_match_manual_cosine(self, tmp_path):
        """Edge weight must equal the analytically computed cosine similarity."""
        vec_a = [1.0, 2.0, 3.0]
        vec_b = [4.0, 5.0, 6.0]
        expected = self._cosine(vec_a, vec_b)

        db_file, conn = self._build_db_with_sessions(tmp_path, [
            {"session_id": "sA", "umap_x": 0.0, "umap_y": 0.0, "metrics_vec": vec_a},
            {"session_id": "sB", "umap_x": 1.0, "umap_y": 1.0, "metrics_vec": vec_b},
        ])
        # Use threshold=0.0 so the edge always appears
        result = self._run_get_similarity_graph(db_file, conn, threshold=0.0)
        assert len(result["edges"]) == 1, "Expected exactly one edge"
        assert abs(result["edges"][0]["weight"] - expected) < 1e-3, (
            f"Edge weight {result['edges'][0]['weight']} != expected {expected:.6f}"
        )

    def test_three_sessions_selective_edges(self, tmp_path):
        """
        Three sessions: only the nearly-parallel pair should produce an edge
        at threshold=0.9.
        """
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [0.99, 0.141, 0.0]  # cosine(a,b) ≈ 0.99 → above 0.9
        vec_c = [0.0, 1.0, 0.0]    # cos(a,c)=0, cos(b,c)≈0.14 → below 0.9

        db_file, conn = self._build_db_with_sessions(tmp_path, [
            {"session_id": "tA", "umap_x": 0.0, "umap_y": 0.0, "metrics_vec": vec_a},
            {"session_id": "tB", "umap_x": 1.0, "umap_y": 0.0, "metrics_vec": vec_b},
            {"session_id": "tC", "umap_x": 0.0, "umap_y": 1.0, "metrics_vec": vec_c},
        ])
        result = self._run_get_similarity_graph(db_file, conn, threshold=0.9)
        edge_pairs = {
            frozenset([e["source"], e["target"]]) for e in result["edges"]
        }
        assert frozenset(["tA", "tB"]) in edge_pairs, "Expected edge between tA and tB"
        assert frozenset(["tA", "tC"]) not in edge_pairs, "Should not have edge tA-tC"
        assert frozenset(["tB", "tC"]) not in edge_pairs, "Should not have edge tB-tC"

    def test_matrix_vs_pairwise_agreement(self, tmp_path):
        """
        Sanity-check: for every emitted edge verify its weight equals the
        pairwise cosine computed outside the function.
        """
        sessions_data = [
            {"session_id": f"v{i}", "umap_x": float(i), "umap_y": 0.0,
             "metrics_vec": [float(i + 1), float(i + 2), float(i + 3)]}
            for i in range(4)
        ]
        db_file, conn = self._build_db_with_sessions(tmp_path, sessions_data)
        result = self._run_get_similarity_graph(db_file, conn, threshold=0.0)

        vecs_by_id = {s["session_id"]: s["metrics_vec"] for s in sessions_data}
        for edge in result["edges"]:
            manual = self._cosine(
                vecs_by_id[edge["source"]], vecs_by_id[edge["target"]]
            )
            assert abs(edge["weight"] - manual) < 1e-3, (
                f"Edge {edge['source']}-{edge['target']}: weight "
                f"{edge['weight']} != manual cosine {manual:.6f}"
            )


# ============================================================
# Fix 6 – Content-Disposition filename sanitisation
# ============================================================

class TestContentDispositionFix:
    """
    server/api/export.py: The session_id is sanitised with re.sub() before
    embedding it in the Content-Disposition header to prevent header injection.
    """

    # Replicate the exact sanitisation regex from export.py
    @staticmethod
    def _sanitize(session_id: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_.-]", "_", session_id)

    def test_semicolon_space_quote_sanitized(self):
        evil = '"; rm -rf /'
        safe = self._sanitize(evil)
        assert '"' not in safe
        assert ';' not in safe
        assert ' ' not in safe

    def test_newline_crlf_stripped(self):
        """CRLF injection in headers – newlines must be replaced."""
        evil = "session\r\nX-Evil: injected"
        safe = self._sanitize(evil)
        assert "\r" not in safe
        assert "\n" not in safe

    def test_path_traversal_chars_stripped(self):
        evil = "../../etc/passwd"
        safe = self._sanitize(evil)
        assert "/" not in safe

    def test_normal_session_id_unchanged(self):
        normal = "session-2024_01.001"
        safe = self._sanitize(normal)
        assert safe == normal

    def test_header_value_contains_exactly_two_quotes(self):
        """
        The Content-Disposition header wraps the filename in double quotes.
        After sanitisation there must be exactly two – the delimiters.
        """
        evil_id = '"; rm -rf /'
        safe_id = self._sanitize(evil_id)
        header_value = f'attachment; filename="{safe_id}.json"'
        assert header_value.count('"') == 2, (
            f"Unexpected quotes in header: {header_value!r}"
        )

    def test_regex_from_export_module_matches_expected(self):
        """The actual regex in export.py must produce the same result as our replication."""
        import server.api.export as export_mod
        import inspect
        source = inspect.getsource(export_mod)
        # Verify the sanitisation pattern is present in the source
        assert r"[^a-zA-Z0-9_.-]" in source, (
            "Expected sanitisation regex not found in export.py"
        )

    def test_export_endpoint_content_disposition(self, tmp_path):
        """
        Integration test: create a FastAPI TestClient, insert a session, call
        the export endpoint, and verify the Content-Disposition header is safe.
        """
        try:
            from fastapi.testclient import TestClient
            import httpx  # noqa – just verify it's importable
        except ImportError:
            pytest.skip("httpx not available for TestClient")

        import server.storage.db as db_mod
        import server.api.export as export_mod

        db_file = tmp_path / "export_test.duckdb"
        conn = make_db_conn(db_file)

        session_id = "my-session_001.v2"  # all-safe chars
        conn.execute(
            "INSERT INTO sessions (session_id, source, start_time, status) VALUES (?, ?, ?, ?)",
            [session_id, "live", 0.0, "complete"],
        )

        async def _run():
            db_instance = build_database_on_conn(conn)
            original_db = export_mod.db
            original_db_mod = db_mod.db
            export_mod.db = db_instance
            db_mod.db = db_instance
            try:
                from fastapi import FastAPI
                app = FastAPI()
                app.include_router(export_mod.router)
                client = TestClient(app)
                response = client.get(f"/sessions/{session_id}/export")
                assert response.status_code == 200
                cd = response.headers.get("content-disposition", "")
                assert f'filename="{session_id}.json"' in cd
                return cd
            finally:
                export_mod.db = original_db
                db_mod.db = original_db_mod

        run(_run())
