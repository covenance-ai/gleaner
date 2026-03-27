"""Tests for gleaner pull: session flattening, Parquet I/O, incremental merge.

Tests the data transformation pipeline without hitting any server.
Requires pyarrow (the 'pull' optional dep).
"""

import json

import pyarrow.parquet as pq
import pytest

from gleaner.pull import _flatten_session, _load_latest_timestamp, _merge_parquet, _save_parquet


def _make_session(session_id, user="alice", project="proj", uploaded_at="2026-03-20T10:00:00+00:00"):
    """Build a minimal session dict like the API returns."""
    return {
        "session_id": session_id,
        "provenance": {"user": user, "host": "laptop", "platform": "Darwin arm64"},
        "project": project,
        "topic": f"topic for {session_id}",
        "cwd": "/home/alice",
        "message_count": 10,
        "user_message_count": 5,
        "assistant_message_count": 5,
        "tool_use_count": 3,
        "tool_counts": {"Read": 2, "Edit": 1},
        "first_timestamp": "2026-03-20T09:50:00Z",
        "last_timestamp": "2026-03-20T10:00:00Z",
        "transcript_size": 5000,
        "transcript_gz_size": 1200,
        "uploaded_at": uploaded_at,
        "redactions": 0,
    }


class TestFlattenSession:
    """_flatten_session turns nested API response into a flat tabular row."""

    def test_provenance_flattened(self):
        row = _flatten_session(_make_session("s1"))
        assert row["user"] == "alice"
        assert row["host"] == "laptop"
        assert "provenance" not in row

    def test_tool_counts_serialized_as_json(self):
        row = _flatten_session(_make_session("s1"))
        parsed = json.loads(row["tool_counts_json"])
        assert parsed == {"Read": 2, "Edit": 1}

    def test_missing_fields_get_defaults(self):
        """Partial session data doesn't crash, gets zero/empty defaults."""
        row = _flatten_session({"session_id": "empty"})
        assert row["message_count"] == 0
        assert row["user"] == ""
        assert row["topic"] == ""

    def test_uploaded_at_datetime_object(self):
        """If uploaded_at is a datetime (not string), it gets converted."""
        from datetime import datetime, timezone
        s = _make_session("s1")
        s["uploaded_at"] = datetime(2026, 3, 20, 10, 0, 0, tzinfo=timezone.utc)
        row = _flatten_session(s)
        assert "2026-03-20" in row["uploaded_at"]


class TestParquetRoundTrip:
    """Data survives save -> load -> merge cycle without loss."""

    def test_save_and_reload(self, tmp_path):
        sessions = [_make_session(f"s{i}", uploaded_at=f"2026-03-2{i}T10:00:00+00:00") for i in range(3)]
        path = tmp_path / "sessions.parquet"
        _save_parquet(sessions, path)

        table = pq.read_table(path)
        assert table.num_rows == 3
        ids = set(table.column("session_id").to_pylist())
        assert ids == {"s0", "s1", "s2"}

    def test_latest_timestamp(self, tmp_path):
        sessions = [
            _make_session("s1", uploaded_at="2026-03-20T10:00:00+00:00"),
            _make_session("s2", uploaded_at="2026-03-22T10:00:00+00:00"),
            _make_session("s3", uploaded_at="2026-03-21T10:00:00+00:00"),
        ]
        path = tmp_path / "sessions.parquet"
        _save_parquet(sessions, path)

        latest = _load_latest_timestamp(path)
        assert latest == "2026-03-22T10:00:00+00:00"

    def test_merge_deduplicates(self, tmp_path):
        """Merging sessions that already exist locally doesn't create duplicates."""
        path = tmp_path / "sessions.parquet"
        _save_parquet([_make_session("s1"), _make_session("s2")], path)

        # "New" batch includes s2 (already exists) and s3 (truly new)
        new = [_make_session("s2"), _make_session("s3")]
        total, added = _merge_parquet(path, new)
        assert added == 1
        assert total == 3

    def test_merge_no_new_sessions(self, tmp_path):
        path = tmp_path / "sessions.parquet"
        _save_parquet([_make_session("s1")], path)

        total, added = _merge_parquet(path, [_make_session("s1")])
        assert added == 0
        assert total == 1

    def test_all_columns_present(self, tmp_path):
        """Saved Parquet contains all expected columns."""
        path = tmp_path / "sessions.parquet"
        _save_parquet([_make_session("s1")], path)
        table = pq.read_table(path)
        expected = {
            "session_id", "user", "host", "platform", "project", "topic",
            "cwd", "message_count", "user_message_count", "assistant_message_count",
            "tool_use_count", "tool_counts_json", "first_timestamp", "last_timestamp",
            "transcript_size", "transcript_gz_size", "uploaded_at", "redactions",
        }
        assert set(table.column_names) == expected
