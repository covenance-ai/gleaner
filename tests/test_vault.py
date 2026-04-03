"""Tests for the local vault storage.

The vault normalizes Claude Code and Cursor sessions into a unified format
at ~/.gleaner/. Tests verify ingestion, normalization, indexing, and
the full collect pipeline.
"""

import json
from pathlib import Path

import pytest

from gleaner.vault import collect, ingest_session, normalize_entry, update_index

pyarrow = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")


# -- Sample data ---------------------------------------------------------------

CLAUDE_CODE_MESSAGES = [
    {
        "type": "user",
        "timestamp": "2026-03-20T10:00:00Z",
        "message": {"content": "Fix the login bug"},
    },
    {
        "type": "assistant",
        "timestamp": "2026-03-20T10:00:05Z",
        "message": {
            "content": [
                {"type": "text", "text": "Let me look at that."},
                {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/src/auth.py"}},
            ]
        },
    },
]

CURSOR_MESSAGES = [
    {
        "role": "user",
        "message": {"content": [{"type": "text", "text": "Add retry logic"}]},
    },
    {
        "role": "assistant",
        "message": {
            "content": [
                {"type": "text", "text": "Done."},
                {"type": "tool_use", "name": "file_edit", "input": {"path": "api.py"}},
            ]
        },
    },
]


def _write_jsonl(path: Path, messages: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(m) for m in messages) + "\n")


# -- normalize_entry -----------------------------------------------------------


class TestNormalizeEntry:
    """normalize_entry converts both IDE formats to {role, ts, content}."""

    def test_claude_code_format(self):
        """Claude Code 'type' field maps to 'role', 'timestamp' to 'ts'."""
        result = normalize_entry(CLAUDE_CODE_MESSAGES[0])
        assert result["role"] == "user"
        assert result["ts"] == "2026-03-20T10:00:00Z"

    def test_cursor_format_has_null_ts(self):
        """Cursor entries have no timestamps — ts is None."""
        result = normalize_entry(CURSOR_MESSAGES[0])
        assert result["role"] == "user"
        assert result["ts"] is None

    def test_string_content_wrapped_in_list(self):
        """String content is normalized to [{type: text, text: ...}]."""
        result = normalize_entry(CLAUDE_CODE_MESSAGES[0])
        assert result["content"] == [{"type": "text", "text": "Fix the login bug"}]

    def test_list_content_preserved(self):
        """List content passes through unchanged."""
        result = normalize_entry(CLAUDE_CODE_MESSAGES[1])
        assert len(result["content"]) == 2
        assert result["content"][0]["type"] == "text"
        assert result["content"][1]["type"] == "tool_use"

    def test_output_keys(self):
        """Normalized entries contain exactly role, ts, content."""
        for entry in [*CLAUDE_CODE_MESSAGES, *CURSOR_MESSAGES]:
            assert set(normalize_entry(entry).keys()) == {"role", "ts", "content"}


# -- ingest_session ------------------------------------------------------------


class TestIngestSession:
    """ingest_session copies raw + creates normalized transcript."""

    def test_creates_files(self, tmp_path):
        """Ingestion creates raw.jsonl and transcript.jsonl."""
        raw = tmp_path / "source" / "s1.jsonl"
        _write_jsonl(raw, CLAUDE_CODE_MESSAGES)

        vault = tmp_path / "vault"
        ingest_session("s1", raw, "claude_code", "proj", vault_dir=vault)

        session_dir = vault / "sessions" / "s1"
        assert (session_dir / "raw.jsonl").exists()
        assert (session_dir / "transcript.jsonl").exists()

    def test_raw_is_exact_copy(self, tmp_path):
        """raw.jsonl is byte-identical to the source file."""
        raw = tmp_path / "source" / "s1.jsonl"
        _write_jsonl(raw, CLAUDE_CODE_MESSAGES)

        vault = tmp_path / "vault"
        ingest_session("s1", raw, "claude_code", "proj", vault_dir=vault)

        assert (vault / "sessions" / "s1" / "raw.jsonl").read_bytes() == raw.read_bytes()

    def test_transcript_lines_normalized(self, tmp_path):
        """Every transcript line has exactly {role, ts, content}."""
        raw = tmp_path / "source" / "s1.jsonl"
        _write_jsonl(raw, CLAUDE_CODE_MESSAGES)

        vault = tmp_path / "vault"
        ingest_session("s1", raw, "claude_code", "proj", vault_dir=vault)

        with open(vault / "sessions" / "s1" / "transcript.jsonl") as f:
            for line in f:
                entry = json.loads(line)
                assert set(entry.keys()) == {"role", "ts", "content"}
                assert isinstance(entry["content"], list)

    def test_line_count_preserved(self, tmp_path):
        """Transcript has same number of lines as raw (no lines dropped)."""
        raw = tmp_path / "source" / "s1.jsonl"
        _write_jsonl(raw, CLAUDE_CODE_MESSAGES)

        vault = tmp_path / "vault"
        ingest_session("s1", raw, "claude_code", "proj", vault_dir=vault)

        raw_lines = [l for l in raw.read_text().splitlines() if l.strip()]
        transcript_lines = [
            l for l in (vault / "sessions" / "s1" / "transcript.jsonl").read_text().splitlines()
            if l.strip()
        ]
        assert len(transcript_lines) == len(raw_lines)

    def test_idempotent(self, tmp_path):
        """Second call returns None, directory unchanged."""
        raw = tmp_path / "source" / "s1.jsonl"
        _write_jsonl(raw, CLAUDE_CODE_MESSAGES)
        vault = tmp_path / "vault"

        assert ingest_session("s1", raw, "claude_code", "proj", vault_dir=vault) is not None
        assert ingest_session("s1", raw, "claude_code", "proj", vault_dir=vault) is None

    def test_skips_worthless(self, tmp_path):
        """Sessions with no user messages are skipped, no directory created."""
        raw = tmp_path / "source" / "empty.jsonl"
        _write_jsonl(raw, [
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
        ])
        vault = tmp_path / "vault"

        assert ingest_session("empty", raw, "claude_code", "proj", vault_dir=vault) is None
        assert not (vault / "sessions" / "empty").exists()

    def test_metadata_fields(self, tmp_path):
        """Returned metadata has expected keys and values."""
        raw = tmp_path / "source" / "s1.jsonl"
        _write_jsonl(raw, CLAUDE_CODE_MESSAGES)
        vault = tmp_path / "vault"

        result = ingest_session("s1", raw, "claude_code", "my-proj", cwd="/work", vault_dir=vault)

        assert result["session_id"] == "s1"
        assert result["ide"] == "claude_code"
        assert result["project"] == "my-proj"
        assert result["cwd"] == "/work"
        assert result["origin"] == "local"
        assert result["message_count"] == 2
        assert result["user_message_count"] == 1
        assert result["tool_use_count"] == 1
        assert json.loads(result["tool_counts_json"]) == {"Read": 1}

    def test_cursor_session(self, tmp_path):
        """Cursor sessions are ingested with correct ide tag."""
        raw = tmp_path / "source" / "c1.jsonl"
        _write_jsonl(raw, CURSOR_MESSAGES)
        vault = tmp_path / "vault"

        result = ingest_session("c1", raw, "cursor", "Users-me-proj", vault_dir=vault)
        assert result["ide"] == "cursor"


# -- update_index --------------------------------------------------------------


class TestUpdateIndex:
    """update_index creates and merges the parquet index."""

    def _row(self, session_id="s1", **overrides):
        base = {
            "session_id": session_id, "ide": "claude_code", "project": "test",
            "topic": "test", "cwd": "", "source": "human", "task_type": "development",
            "user": "me", "host": "here", "platform": "Darwin arm64",
            "message_count": 2, "user_message_count": 1, "assistant_message_count": 1,
            "tool_use_count": 0, "tool_counts_json": "{}",
            "first_timestamp": "2026-01-01T00:00:00Z",
            "last_timestamp": "2026-01-01T00:01:00Z",
            "transcript_size": 100, "ingested_at": "2026-01-01T00:00:00Z",
            "origin": "local",
        }
        base.update(overrides)
        return base

    def test_creates_new_index(self, tmp_path):
        """Creates index.parquet when none exists."""
        assert update_index([self._row()], vault_dir=tmp_path) == 1
        assert (tmp_path / "index.parquet").exists()

    def test_merges(self, tmp_path):
        """New sessions are appended to existing index."""
        update_index([self._row("s1")], vault_dir=tmp_path)
        assert update_index([self._row("s2")], vault_dir=tmp_path) == 1
        assert pq.read_table(tmp_path / "index.parquet").num_rows == 2

    def test_deduplicates(self, tmp_path):
        """Existing session_ids are not added again."""
        update_index([self._row("s1")], vault_dir=tmp_path)
        assert update_index([self._row("s1")], vault_dir=tmp_path) == 0
        assert pq.read_table(tmp_path / "index.parquet").num_rows == 1

    def test_empty_is_noop(self, tmp_path):
        """Empty input does nothing."""
        assert update_index([], vault_dir=tmp_path) == 0
        assert not (tmp_path / "index.parquet").exists()

    def test_columns_roundtrip(self, tmp_path):
        """All metadata columns survive parquet write/read."""
        row = self._row()
        update_index([row], vault_dir=tmp_path)
        table = pq.read_table(tmp_path / "index.parquet")
        assert set(table.column_names) == set(row.keys())


# -- collect -------------------------------------------------------------------


def _setup_claude(claude_dir, project, session_id, messages):
    path = claude_dir / "projects" / project / f"{session_id}.jsonl"
    _write_jsonl(path, messages)


def _setup_cursor(cursor_dir, project, session_id, messages):
    d = cursor_dir / "projects" / project / "agent-transcripts" / session_id
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{session_id}.jsonl").write_text(
        "\n".join(json.dumps(m) for m in messages) + "\n"
    )


class TestCollect:
    """collect scans IDE directories and populates the vault."""

    def test_claude_code(self, tmp_path, monkeypatch):
        """Claude Code sessions are discovered and ingested."""
        vault = tmp_path / "vault"
        claude = tmp_path / "claude"
        monkeypatch.setattr("gleaner.vault.CLAUDE_DIR", claude)
        monkeypatch.setattr("gleaner.cursor.CURSOR_DIR", tmp_path / "no-cursor")

        _setup_claude(claude, "my-proj", "cc-1", CLAUDE_CODE_MESSAGES)

        assert collect(vault_dir=vault) == 1
        assert (vault / "sessions" / "cc-1" / "raw.jsonl").exists()
        assert (vault / "sessions" / "cc-1" / "transcript.jsonl").exists()
        assert (vault / "index.parquet").exists()

    def test_cursor(self, tmp_path, monkeypatch):
        """Cursor sessions are discovered and ingested."""
        vault = tmp_path / "vault"
        cursor = tmp_path / "cursor"
        monkeypatch.setattr("gleaner.vault.CLAUDE_DIR", tmp_path / "no-claude")
        monkeypatch.setattr("gleaner.cursor.CURSOR_DIR", cursor)

        _setup_cursor(cursor, "Users-me-proj", "cur-1", CURSOR_MESSAGES)

        assert collect(vault_dir=vault) == 1
        assert (vault / "sessions" / "cur-1" / "raw.jsonl").exists()

    def test_both_ides(self, tmp_path, monkeypatch):
        """Sessions from both IDEs end up in the same vault."""
        vault = tmp_path / "vault"
        claude = tmp_path / "claude"
        cursor = tmp_path / "cursor"
        monkeypatch.setattr("gleaner.vault.CLAUDE_DIR", claude)
        monkeypatch.setattr("gleaner.cursor.CURSOR_DIR", cursor)

        _setup_claude(claude, "proj", "cc-1", CLAUDE_CODE_MESSAGES)
        _setup_cursor(cursor, "proj", "cur-1", CURSOR_MESSAGES)

        assert collect(vault_dir=vault) == 2

        table = pq.read_table(vault / "index.parquet")
        assert set(table.column("ide").to_pylist()) == {"claude_code", "cursor"}

    def test_idempotent(self, tmp_path, monkeypatch):
        """Running collect twice adds nothing on the second run."""
        vault = tmp_path / "vault"
        claude = tmp_path / "claude"
        monkeypatch.setattr("gleaner.vault.CLAUDE_DIR", claude)
        monkeypatch.setattr("gleaner.cursor.CURSOR_DIR", tmp_path / "no-cursor")

        _setup_claude(claude, "proj", "s1", CLAUDE_CODE_MESSAGES)

        assert collect(vault_dir=vault) == 1
        assert collect(vault_dir=vault) == 0
        assert pq.read_table(vault / "index.parquet").num_rows == 1

    def test_incremental(self, tmp_path, monkeypatch):
        """New sessions are picked up on subsequent runs."""
        vault = tmp_path / "vault"
        claude = tmp_path / "claude"
        monkeypatch.setattr("gleaner.vault.CLAUDE_DIR", claude)
        monkeypatch.setattr("gleaner.cursor.CURSOR_DIR", tmp_path / "no-cursor")

        _setup_claude(claude, "proj", "s1", CLAUDE_CODE_MESSAGES)
        assert collect(vault_dir=vault) == 1

        _setup_claude(claude, "proj", "s2", CLAUDE_CODE_MESSAGES)
        assert collect(vault_dir=vault) == 1
        assert pq.read_table(vault / "index.parquet").num_rows == 2

    def test_skips_worthless(self, tmp_path, monkeypatch):
        """Worthless sessions (no user messages) are not collected."""
        vault = tmp_path / "vault"
        claude = tmp_path / "claude"
        monkeypatch.setattr("gleaner.vault.CLAUDE_DIR", claude)
        monkeypatch.setattr("gleaner.cursor.CURSOR_DIR", tmp_path / "no-cursor")

        worthless = [{"type": "assistant", "message": {"content": "hi"}}]
        _setup_claude(claude, "proj", "bad", worthless)

        assert collect(vault_dir=vault) == 0
        assert not (vault / "sessions" / "bad").exists()
