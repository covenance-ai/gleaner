"""Tests for the local vault storage backend (db_local).

Verifies that db_local reads from a parquet index + JSONL files and
returns data in the same shape as db_mock, so the frontend works
identically in local mode.
"""

import gzip
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")


def _make_row(session_id="s1", user="testuser", project="test-proj", **overrides):
    now = datetime.now(timezone.utc)
    base = {
        "session_id": session_id,
        "ide": "claude_code",
        "project": project,
        "topic": f"Topic for {session_id}",
        "cwd": "/work",
        "source": "human",
        "task_type": "development",
        "user": user,
        "host": "MacBook",
        "platform": "Darwin arm64",
        "message_count": 4,
        "user_message_count": 2,
        "assistant_message_count": 2,
        "tool_use_count": 3,
        "tool_counts_json": json.dumps({"Read": 2, "Edit": 1}),
        "first_timestamp": (now - timedelta(hours=1)).isoformat(),
        "last_timestamp": now.isoformat(),
        "transcript_size": 5000,
        "ingested_at": now.isoformat(),
        "origin": "local",
    }
    base.update(overrides)
    return base


def _write_vault(vault_dir: Path, rows: list[dict], transcripts: dict[str, list[dict]] | None = None):
    """Build a test vault with parquet index and optional JSONL sessions."""
    vault_dir.mkdir(parents=True, exist_ok=True)
    if rows:
        table = pa.Table.from_pylist(rows)
        pq.write_table(table, vault_dir / "index.parquet")

    if transcripts:
        for sid, messages in transcripts.items():
            session_dir = vault_dir / "sessions" / sid
            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / "raw.jsonl").write_text(
                "\n".join(json.dumps(m) for m in messages) + "\n"
            )


@pytest.fixture
def db_local(tmp_path, monkeypatch):
    """Import db_local with VAULT_DIR pointing to tmp_path."""
    from server import db_local
    monkeypatch.setattr(db_local, "VAULT_DIR", tmp_path)
    # Reset cache so each test starts fresh
    db_local._index_cache = None
    db_local._index_mtime = 0
    return db_local


# --- Empty vault ---


class TestEmptyVault:
    """All functions return valid empty structures when vault has no data."""

    def test_list_sessions(self, db_local):
        assert db_local.list_sessions() == []

    def test_get_session(self, db_local):
        assert db_local.get_session("nonexistent") is None

    def test_get_transcript(self, db_local):
        assert db_local.get_session_transcript("nonexistent") is None

    def test_get_user_stats(self, db_local):
        stats = db_local.get_user_stats("nobody")
        assert stats["total_sessions"] == 0
        assert stats["last_session"] is None
        assert stats["heatmap"] == [] or all(d["count"] == 0 for d in stats["heatmap"])

    def test_get_stats(self, db_local):
        stats = db_local.get_stats()
        assert stats["total_sessions"] == 0
        assert stats["users"] == []


# --- Session operations ---


class TestListSessions:
    """list_sessions reads from parquet with filters, sorting, and limits."""

    def test_returns_all(self, db_local, tmp_path):
        _write_vault(tmp_path, [_make_row("s1"), _make_row("s2")])
        result = db_local.list_sessions()
        assert len(result) == 2

    def test_filter_by_user(self, db_local, tmp_path):
        _write_vault(tmp_path, [_make_row("s1", user="alice"), _make_row("s2", user="bob")])
        result = db_local.list_sessions(user="alice")
        assert len(result) == 1
        assert result[0]["provenance"]["user"] == "alice"

    def test_filter_by_project(self, db_local, tmp_path):
        _write_vault(tmp_path, [_make_row("s1", project="p1"), _make_row("s2", project="p2")])
        result = db_local.list_sessions(project="p1")
        assert len(result) == 1
        assert result[0]["project"] == "p1"

    def test_limit(self, db_local, tmp_path):
        _write_vault(tmp_path, [_make_row(f"s{i}") for i in range(10)])
        result = db_local.list_sessions(limit=3)
        assert len(result) == 3

    def test_ids_only(self, db_local, tmp_path):
        _write_vault(tmp_path, [_make_row("s1"), _make_row("s2")])
        result = db_local.list_sessions(ids_only=True)
        assert set(result) == {"s1", "s2"}

    def test_sorted_newest_first(self, db_local, tmp_path):
        now = datetime.now(timezone.utc)
        _write_vault(tmp_path, [
            _make_row("old", first_timestamp=(now - timedelta(days=2)).isoformat()),
            _make_row("new", first_timestamp=now.isoformat()),
        ])
        result = db_local.list_sessions()
        assert result[0]["session_id"] == "new"

    def test_tool_counts_excluded_by_default(self, db_local, tmp_path):
        _write_vault(tmp_path, [_make_row("s1")])
        result = db_local.list_sessions()
        assert "tool_counts" not in result[0]

    def test_tool_counts_included_when_requested(self, db_local, tmp_path):
        _write_vault(tmp_path, [_make_row("s1")])
        result = db_local.list_sessions(keep_tool_counts=True)
        assert "tool_counts" in result[0]
        assert result[0]["tool_counts"]["Read"] == 2


class TestGetSession:
    """get_session returns a single session with tool_counts parsed."""

    def test_found(self, db_local, tmp_path):
        _write_vault(tmp_path, [_make_row("s1")])
        result = db_local.get_session("s1")
        assert result["session_id"] == "s1"
        assert result["tool_counts"] == {"Read": 2, "Edit": 1}
        assert result["provenance"]["host"] == "MacBook"

    def test_not_found(self, db_local, tmp_path):
        _write_vault(tmp_path, [_make_row("s1")])
        assert db_local.get_session("nope") is None


class TestGetTranscript:
    """get_session_transcript returns gzipped raw JSONL."""

    def test_returns_valid_gzip(self, db_local, tmp_path):
        messages = [
            {"type": "user", "timestamp": "2026-01-01T00:00:00Z",
             "message": {"content": "hello"}},
            {"type": "assistant", "timestamp": "2026-01-01T00:00:05Z",
             "message": {"content": "hi"}},
        ]
        _write_vault(tmp_path, [_make_row("s1")], transcripts={"s1": messages})
        data = db_local.get_session_transcript("s1")
        assert data is not None
        decompressed = gzip.decompress(data).decode()
        lines = [json.loads(l) for l in decompressed.strip().split("\n")]
        assert len(lines) == 2
        assert lines[0]["type"] == "user"


# --- Stats ---


class TestGetUserStats:
    """get_user_stats computes personal analytics from parquet."""

    def test_shape_matches_frontend_expectations(self, db_local, tmp_path):
        """Output has all fields that home.js reads."""
        _write_vault(tmp_path, [_make_row("s1")])
        stats = db_local.get_user_stats("testuser")

        assert "user" in stats
        assert "total_sessions" in stats
        assert "avg_messages_per_session" in stats
        assert "last_session" in stats
        assert "week_stats" in stats
        assert "heatmap" in stats
        assert "tool_usage" in stats
        assert "project_usage" in stats
        assert "recent_sessions" in stats

        ws = stats["week_stats"]
        for key in ("sessions", "sessions_prev_week", "messages",
                     "avg_duration_seconds", "total_duration_seconds",
                     "active_days", "most_active_project"):
            assert key in ws, f"week_stats missing {key}"

    def test_totals(self, db_local, tmp_path):
        _write_vault(tmp_path, [
            _make_row("s1", message_count=10),
            _make_row("s2", message_count=20),
        ])
        stats = db_local.get_user_stats("testuser")
        assert stats["total_sessions"] == 2
        assert stats["avg_messages_per_session"] == 15

    def test_tool_usage_aggregated(self, db_local, tmp_path):
        _write_vault(tmp_path, [
            _make_row("s1", tool_counts_json=json.dumps({"Read": 5, "Edit": 2})),
            _make_row("s2", tool_counts_json=json.dumps({"Read": 3, "Bash": 1})),
        ])
        stats = db_local.get_user_stats("testuser")
        assert stats["tool_usage"]["Read"] == 8
        assert stats["tool_usage"]["Edit"] == 2
        assert stats["tool_usage"]["Bash"] == 1

    def test_last_session_has_provenance(self, db_local, tmp_path):
        _write_vault(tmp_path, [_make_row("s1")])
        stats = db_local.get_user_stats("testuser")
        ls = stats["last_session"]
        assert ls is not None
        assert "provenance" in ls
        assert ls["provenance"]["host"] == "MacBook"


class TestGetStats:
    """get_stats computes global analytics from parquet."""

    def test_shape_matches_frontend_expectations(self, db_local, tmp_path):
        """Output has all fields that team.js reads."""
        _write_vault(tmp_path, [_make_row("s1")])
        stats = db_local.get_stats()

        for key in ("total_sessions", "total_messages", "total_tool_uses",
                     "unique_users", "unique_projects", "avg_duration_seconds",
                     "active_this_week", "users", "projects", "tool_usage",
                     "timeline", "user_stats", "project_stats", "recent_sessions"):
            assert key in stats, f"get_stats missing {key}"

    def test_user_stats_shape(self, db_local, tmp_path):
        _write_vault(tmp_path, [_make_row("s1")])
        stats = db_local.get_stats()
        for username, us in stats["user_stats"].items():
            for key in ("sessions", "messages", "tool_uses", "last_active",
                         "avg_duration_seconds", "top_project", "active_days_this_week"):
                assert key in us, f"user_stats[{username}] missing {key}"

    def test_multi_user(self, db_local, tmp_path):
        _write_vault(tmp_path, [
            _make_row("s1", user="alice"),
            _make_row("s2", user="bob"),
            _make_row("s3", user="alice"),
        ])
        stats = db_local.get_stats()
        assert stats["unique_users"] == 2
        assert stats["user_stats"]["alice"]["sessions"] == 2
        assert stats["user_stats"]["bob"]["sessions"] == 1

    def test_timeline_has_30_days(self, db_local, tmp_path):
        _write_vault(tmp_path, [_make_row("s1")])
        stats = db_local.get_stats()
        assert len(stats["timeline"]) == 30


# --- Token/user stubs ---


class TestStubs:
    """Auth stubs return appropriate values for local mode."""

    def test_validate_token_always_succeeds(self, db_local):
        result = db_local.validate_token("anything")
        assert result["active"] is True

    def test_store_session_raises(self, db_local):
        with pytest.raises(NotImplementedError):
            db_local.store_session("x", {}, {}, b"", 0)

    def test_list_tokens_empty(self, db_local):
        assert db_local.list_tokens() == []

    def test_list_user_tokens_empty(self, db_local):
        assert db_local.list_user_tokens("x@x.com") == []
