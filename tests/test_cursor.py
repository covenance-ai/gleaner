"""Tests for Cursor session discovery and transcript parsing.

Verifies that Cursor's agent-transcript JSONL format (role-based, no timestamps)
is correctly handled by the shared parse_transcript pipeline, and that
cursor-specific session discovery works.
"""

import json
from pathlib import Path

from gleaner.cursor import find_all_cursor_sessions, find_cursor_session_file
from gleaner.tags import tag_session
from gleaner.upload import parse_transcript


# -- Fixtures for Cursor-format transcripts ----------------------------------


def _cursor_transcript(messages: list[dict], tmp_path: Path, session_id: str = "abc-123") -> Path:
    """Write a Cursor-style JSONL transcript to the expected directory layout."""
    session_dir = tmp_path / "projects" / "Users-me-myproject" / "agent-transcripts" / session_id
    session_dir.mkdir(parents=True)
    path = session_dir / f"{session_id}.jsonl"
    path.write_text("\n".join(json.dumps(m) for m in messages) + "\n")
    return path


SAMPLE_CURSOR_MESSAGES = [
    {
        "role": "user",
        "message": {"content": [{"type": "text", "text": "Add a retry to the API call"}]},
    },
    {
        "role": "assistant",
        "message": {
            "content": [
                {"type": "text", "text": "I'll add retry logic."},
                {"type": "tool_use", "name": "file_edit", "input": {"path": "api.py"}},
            ]
        },
    },
    {
        "role": "user",
        "message": {"content": [{"type": "text", "text": "Looks good, run tests"}]},
    },
    {
        "role": "assistant",
        "message": {
            "content": [
                {"type": "text", "text": "Running tests now."},
                {"type": "tool_use", "name": "terminal", "input": {"command": "pytest"}},
                {"type": "tool_use", "name": "file_edit", "input": {"path": "test_api.py"}},
            ]
        },
    },
]


class TestCursorParseTranscript:
    """parse_transcript handles Cursor's role-based JSONL format."""

    def test_counts_match_cursor_format(self, tmp_path):
        """Cursor transcripts using 'role' instead of 'type' produce correct counts."""
        path = _cursor_transcript(SAMPLE_CURSOR_MESSAGES, tmp_path)
        meta = parse_transcript(path)
        assert meta["message_count"] == 4
        assert meta["user_message_count"] == 2
        assert meta["assistant_message_count"] == 2

    def test_tool_use_extraction(self, tmp_path):
        """Tool uses are extracted from Cursor assistant messages."""
        path = _cursor_transcript(SAMPLE_CURSOR_MESSAGES, tmp_path)
        meta = parse_transcript(path)
        assert meta["tool_use_count"] == 3
        assert meta["tool_counts"] == {"file_edit": 2, "terminal": 1}

    def test_topic_from_first_user_message(self, tmp_path):
        """Topic is extracted from the first user message content block."""
        path = _cursor_transcript(SAMPLE_CURSOR_MESSAGES, tmp_path)
        meta = parse_transcript(path)
        assert meta["topic"] == "Add a retry to the API call"

    def test_timestamps_from_file_when_missing(self, tmp_path):
        """When JSONL has no timestamp fields, file metadata is used."""
        path = _cursor_transcript(SAMPLE_CURSOR_MESSAGES, tmp_path)
        meta = parse_transcript(path)
        # Should have timestamps from file metadata (not None)
        assert meta["first_timestamp"] is not None
        assert meta["last_timestamp"] is not None
        assert meta["first_timestamp"] <= meta["last_timestamp"]

    def test_no_assistant_still_valuable(self, tmp_path):
        """Sessions with user messages but no assistant are not worthless."""
        messages = [
            {"role": "user", "message": {"content": [{"type": "text", "text": "hello"}]}},
        ]
        path = _cursor_transcript(messages, tmp_path, session_id="no-assistant")
        meta = parse_transcript(path)
        assert meta["worthless"] is False

    def test_worthless_when_no_user_messages(self, tmp_path):
        """Sessions with zero user messages are worthless."""
        messages = [
            {"role": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
        ]
        path = _cursor_transcript(messages, tmp_path, session_id="no-user")
        meta = parse_transcript(path)
        assert meta["worthless"] is True

    def test_mixed_format_resilience(self, tmp_path):
        """parse_transcript handles a mix of role-based and type-based entries.

        This shouldn't happen in practice but verifies the parser is robust.
        """
        messages = [
            {"type": "user", "timestamp": "2026-01-01T00:00:00Z", "message": {"content": "hello"}},
            {"role": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
        ]
        path = _cursor_transcript(messages, tmp_path, session_id="mixed")
        meta = parse_transcript(path)
        assert meta["user_message_count"] == 1
        assert meta["assistant_message_count"] == 1

    def test_tool_count_equals_sum(self, tmp_path):
        """tool_use_count == sum(tool_counts.values()) for Cursor transcripts."""
        path = _cursor_transcript(SAMPLE_CURSOR_MESSAGES, tmp_path)
        meta = parse_transcript(path)
        assert meta["tool_use_count"] == sum(meta["tool_counts"].values())


class TestCursorSessionDiscovery:
    """find_all_cursor_sessions scans the Cursor directory layout."""

    def test_finds_sessions(self, tmp_path, monkeypatch):
        """Discovers sessions in the standard agent-transcripts layout."""
        monkeypatch.setattr("gleaner.cursor.CURSOR_DIR", tmp_path)
        _cursor_transcript(SAMPLE_CURSOR_MESSAGES, tmp_path, session_id="sess-1")
        sessions = find_all_cursor_sessions()
        assert len(sessions) == 1
        sid, proj, path = sessions[0]
        assert sid == "sess-1"
        assert proj == "Users-me-myproject"
        assert path.name == "sess-1.jsonl"

    def test_multiple_projects(self, tmp_path, monkeypatch):
        """Finds sessions across multiple project directories."""
        monkeypatch.setattr("gleaner.cursor.CURSOR_DIR", tmp_path)

        for proj in ["Users-me-projA", "Users-me-projB"]:
            for sid in ["s1", "s2"]:
                d = tmp_path / "projects" / proj / "agent-transcripts" / sid
                d.mkdir(parents=True)
                (d / f"{sid}.jsonl").write_text('{"role":"user","message":{"content":"hi"}}\n')

        sessions = find_all_cursor_sessions()
        assert len(sessions) == 4
        projects = {s[1] for s in sessions}
        assert projects == {"Users-me-projA", "Users-me-projB"}

    def test_project_filter(self, tmp_path, monkeypatch):
        """--project filter narrows results."""
        monkeypatch.setattr("gleaner.cursor.CURSOR_DIR", tmp_path)

        for proj in ["Users-me-projA", "Users-me-projB"]:
            d = tmp_path / "projects" / proj / "agent-transcripts" / "s1"
            d.mkdir(parents=True)
            (d / "s1.jsonl").write_text('{"role":"user","message":{"content":"hi"}}\n')

        sessions = find_all_cursor_sessions(project_filter="projA")
        assert len(sessions) == 1
        assert sessions[0][1] == "Users-me-projA"

    def test_empty_when_no_projects_dir(self, tmp_path, monkeypatch):
        """Returns empty when ~/.cursor/projects/ doesn't exist."""
        monkeypatch.setattr("gleaner.cursor.CURSOR_DIR", tmp_path)
        assert find_all_cursor_sessions() == []

    def test_skips_projects_without_transcripts(self, tmp_path, monkeypatch):
        """Projects with no agent-transcripts dir are skipped."""
        monkeypatch.setattr("gleaner.cursor.CURSOR_DIR", tmp_path)
        (tmp_path / "projects" / "Users-me-empty" / "repo.json").parent.mkdir(parents=True)
        assert find_all_cursor_sessions() == []


class TestCursorTagging:
    """Cursor sessions are tagged with ide='cursor' and appropriate source/task_type."""

    def test_cursor_human_development(self):
        tags = tag_session("Users-me-myproject", "fix login bug", "raven", "/home", ide="cursor")
        assert tags["source"] == "human"
        assert tags["task_type"] == "development"
        assert tags["ide"] == "cursor"

    def test_cursor_kodo_benchmark(self):
        """Cursor benchmark runs under kodo are classified as kodo/swe_bench."""
        tags = tag_session(
            "Users-ikamen-kodo-benchmark-work-astropy-astropy-12907-cursor",
            "Fix the following issue.",
            "raven", "",
            ide="cursor",
        )
        assert tags["source"] == "kodo"
        assert tags["task_type"] == "swe_bench"

    def test_cursor_kodo_by_topic(self):
        """Kodo topic patterns work for cursor sessions too."""
        tags = tag_session(
            "Users-me-some-proj",
            "Fix the following GitHub issue in this repository.",
            "raven", "",
            ide="cursor",
        )
        assert tags["source"] == "kodo"
        assert tags["task_type"] == "swe_bench"

    def test_default_ide_is_claude_code(self):
        """Without ide kwarg, default is claude_code."""
        tags = tag_session("my-proj", "hello", "raven", "/home")
        assert tags["ide"] == "claude_code"


class TestFindCursorSessionFile:
    """find_cursor_session_file locates transcripts by conversation ID."""

    def test_finds_existing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("gleaner.cursor.CURSOR_DIR", tmp_path)
        d = tmp_path / "projects" / "my-proj" / "agent-transcripts" / "conv-123"
        d.mkdir(parents=True)
        expected = d / "conv-123.jsonl"
        expected.write_text("{}\n")
        assert find_cursor_session_file("conv-123") == expected

    def test_returns_none_for_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("gleaner.cursor.CURSOR_DIR", tmp_path)
        (tmp_path / "projects" / "proj" / "agent-transcripts").mkdir(parents=True)
        assert find_cursor_session_file("nonexistent") is None

    def test_returns_none_when_no_projects(self, tmp_path, monkeypatch):
        monkeypatch.setattr("gleaner.cursor.CURSOR_DIR", tmp_path)
        assert find_cursor_session_file("anything") is None


class TestCursorUploadHook:
    """cursor_upload.main() processes Cursor stop events correctly."""

    def _make_transcript(self, tmp_path, conv_id="conv-abc"):
        """Create a Cursor transcript and return its path."""
        d = tmp_path / "projects" / "my-proj" / "agent-transcripts" / conv_id
        d.mkdir(parents=True)
        path = d / f"{conv_id}.jsonl"
        messages = [
            {"role": "user", "message": {"content": [{"type": "text", "text": "fix bug"}]}},
            {"role": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}},
        ]
        path.write_text("\n".join(json.dumps(m) for m in messages) + "\n")
        return path

    def test_sets_aborted_from_status(self, tmp_path, monkeypatch):
        """aborted=True when stop status is 'aborted'."""
        self._make_transcript(tmp_path)
        monkeypatch.setattr("gleaner.cursor.CURSOR_DIR", tmp_path)

        captured = {}
        def fake_upload(sid, metadata, path):
            captured.update(metadata)
        monkeypatch.setattr("gleaner.cursor_upload.upload", fake_upload)
        monkeypatch.setattr("gleaner.cursor_upload.get_credentials", lambda: ("http://x", "tok"))

        import io
        payload = json.dumps({
            "conversation_id": "conv-abc",
            "status": "aborted",
            "workspace_roots": ["/home/me/proj"],
        })
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))

        from gleaner.cursor_upload import main
        main()

        assert captured["aborted"] is True
        assert captured["has_errors"] is False
        assert captured["ide"] == "cursor"
        assert captured["cwd"] == "/home/me/proj"

    def test_sets_has_errors_from_status(self, tmp_path, monkeypatch):
        """has_errors=True when stop status is 'error'."""
        self._make_transcript(tmp_path)
        monkeypatch.setattr("gleaner.cursor.CURSOR_DIR", tmp_path)

        captured = {}
        def fake_upload(sid, metadata, path):
            captured.update(metadata)
        monkeypatch.setattr("gleaner.cursor_upload.upload", fake_upload)
        monkeypatch.setattr("gleaner.cursor_upload.get_credentials", lambda: ("http://x", "tok"))

        import io
        payload = json.dumps({
            "conversation_id": "conv-abc",
            "status": "error",
            "workspace_roots": [],
        })
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))

        from gleaner.cursor_upload import main
        main()

        assert captured["has_errors"] is True
        assert captured["aborted"] is False

    def test_completed_has_no_flags(self, tmp_path, monkeypatch):
        """Completed sessions have aborted=False, has_errors=False."""
        self._make_transcript(tmp_path)
        monkeypatch.setattr("gleaner.cursor.CURSOR_DIR", tmp_path)

        captured = {}
        def fake_upload(sid, metadata, path):
            captured.update(metadata)
        monkeypatch.setattr("gleaner.cursor_upload.upload", fake_upload)
        monkeypatch.setattr("gleaner.cursor_upload.get_credentials", lambda: ("http://x", "tok"))

        import io
        payload = json.dumps({
            "conversation_id": "conv-abc",
            "status": "completed",
            "workspace_roots": ["/proj"],
        })
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))

        from gleaner.cursor_upload import main
        main()

        assert captured["aborted"] is False
        assert captured["has_errors"] is False

    def test_skips_worthless(self, tmp_path, monkeypatch):
        """Sessions with no user messages are not uploaded."""
        d = tmp_path / "projects" / "my-proj" / "agent-transcripts" / "conv-empty"
        d.mkdir(parents=True)
        (d / "conv-empty.jsonl").write_text(
            json.dumps({"role": "assistant", "message": {"content": "hi"}}) + "\n"
        )
        monkeypatch.setattr("gleaner.cursor.CURSOR_DIR", tmp_path)
        monkeypatch.setattr("gleaner.cursor_upload.get_credentials", lambda: ("http://x", "tok"))

        uploaded = []
        monkeypatch.setattr("gleaner.cursor_upload.upload", lambda *a: uploaded.append(1))

        import io
        payload = json.dumps({"conversation_id": "conv-empty", "status": "completed"})
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))

        from gleaner.cursor_upload import main
        main()

        assert uploaded == []

    def test_skips_missing_conversation_id(self, tmp_path, monkeypatch):
        """No conversation_id in payload → silent return."""
        monkeypatch.setattr("gleaner.cursor_upload.get_credentials", lambda: ("http://x", "tok"))

        uploaded = []
        monkeypatch.setattr("gleaner.cursor_upload.upload", lambda *a: uploaded.append(1))

        import io
        monkeypatch.setattr("sys.stdin", io.StringIO("{}"))

        from gleaner.cursor_upload import main
        main()

        assert uploaded == []
