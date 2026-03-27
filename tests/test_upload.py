"""Tests for gleaner.upload: transcript parsing, provenance, session discovery."""

import json
from pathlib import Path

from gleaner.upload import collect_provenance, find_session_file, parse_transcript


class TestParseTranscript:
    """parse_transcript should extract consistent metadata from JSONL files."""

    def test_counts_are_consistent(self, sample_transcript):
        """Total messages >= user + assistant (there may be other types)."""
        meta = parse_transcript(sample_transcript)
        assert meta["message_count"] >= meta["user_message_count"] + meta["assistant_message_count"]

    def test_tool_count_matches_tool_counts_dict(self, sample_transcript):
        """tool_use_count == sum of all per-tool counts."""
        meta = parse_transcript(sample_transcript)
        assert meta["tool_use_count"] == sum(meta["tool_counts"].values())

    def test_known_counts(self, sample_transcript):
        """Verify exact counts for the sample transcript."""
        meta = parse_transcript(sample_transcript)
        assert meta["message_count"] == 4
        assert meta["user_message_count"] == 2
        assert meta["assistant_message_count"] == 2
        assert meta["tool_use_count"] == 3
        assert meta["tool_counts"] == {"Read": 1, "Edit": 1, "Bash": 1}

    def test_topic_from_first_user_message(self, sample_transcript):
        """Topic is extracted from the first user message."""
        meta = parse_transcript(sample_transcript)
        assert meta["topic"] == "Fix the login bug"

    def test_timestamps_ordered(self, sample_transcript):
        """first_timestamp <= last_timestamp."""
        meta = parse_transcript(sample_transcript)
        assert meta["first_timestamp"] <= meta["last_timestamp"]

    def test_topic_truncated_at_200(self, tmp_jsonl):
        """Long topics are truncated to 200 chars + ellipsis."""
        long_msg = "x" * 300
        path = tmp_jsonl([
            {"type": "user", "message": {"content": long_msg}},
        ])
        meta = parse_transcript(path)
        assert len(meta["topic"]) == 203  # 200 + "..."
        assert meta["topic"].endswith("...")

    def test_empty_file(self, tmp_jsonl):
        """Empty files produce zero counts."""
        path = tmp_jsonl([])
        # write an actually empty file
        path.write_text("")
        meta = parse_transcript(path)
        assert meta["message_count"] == 0
        assert meta["tool_use_count"] == 0
        assert meta["topic"] == ""

    def test_malformed_lines_skipped(self, tmp_jsonl):
        """Invalid JSON lines are silently skipped."""
        path = tmp_jsonl([{"type": "user", "message": {"content": "hello"}}])
        # Append garbage
        with open(path, "a") as f:
            f.write("not json\n{broken\n")
        meta = parse_transcript(path)
        assert meta["message_count"] == 1


class TestCollectProvenance:
    """collect_provenance returns the expected keys."""

    def test_keys(self):
        p = collect_provenance()
        assert set(p.keys()) == {"user", "host", "platform"}

    def test_values_are_strings(self):
        p = collect_provenance()
        assert all(isinstance(v, str) for v in p.values())

    def test_platform_has_system_and_arch(self):
        """Platform string contains system and machine architecture."""
        p = collect_provenance()
        parts = p["platform"].split()
        assert len(parts) == 2  # e.g. "Darwin arm64"


class TestFindSessionFile:
    """find_session_file locates JSONL files inside ~/.claude/projects/."""

    def test_finds_existing_session(self, tmp_path, monkeypatch):
        """Finds a session file in the expected directory structure."""
        projects = tmp_path / "projects" / "my-project"
        projects.mkdir(parents=True)
        session_file = projects / "abc123.jsonl"
        session_file.write_text("{}\n")

        monkeypatch.setattr("gleaner.upload.CLAUDE_DIR", tmp_path)
        assert find_session_file("abc123") == session_file

    def test_returns_none_for_missing(self, tmp_path, monkeypatch):
        """Returns None when session doesn't exist."""
        projects = tmp_path / "projects" / "proj"
        projects.mkdir(parents=True)

        monkeypatch.setattr("gleaner.upload.CLAUDE_DIR", tmp_path)
        assert find_session_file("nonexistent") is None

    def test_returns_none_when_no_projects_dir(self, tmp_path, monkeypatch):
        """Returns None when ~/.claude/projects/ doesn't exist."""
        monkeypatch.setattr("gleaner.upload.CLAUDE_DIR", tmp_path)
        assert find_session_file("anything") is None
