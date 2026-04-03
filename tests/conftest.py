"""Shared fixtures for gleaner tests."""

import json
import os
import sys
from pathlib import Path

import pytest

# Set mock mode before any server import
os.environ["GLEANER_MOCK"] = "1"

# Make server package importable from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def tmp_jsonl(tmp_path):
    """Create a temporary JSONL transcript file with configurable messages."""

    def _make(messages: list[dict], filename: str = "session.jsonl") -> Path:
        path = tmp_path / filename
        path.write_text("\n".join(json.dumps(m) for m in messages) + "\n")
        return path

    return _make


@pytest.fixture
def sample_transcript(tmp_jsonl):
    """A realistic multi-message transcript file."""
    messages = [
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
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "Read",
                        "input": {"file_path": "/src/auth.py"},
                    },
                ]
            },
        },
        {
            "type": "user",
            "timestamp": "2026-03-20T10:00:10Z",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "content": "file contents here",
                    }
                ]
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-03-20T10:01:00Z",
            "message": {
                "content": [
                    {"type": "text", "text": "Found it. Fixing now."},
                    {
                        "type": "tool_use",
                        "id": "t2",
                        "name": "Edit",
                        "input": {"file_path": "/src/auth.py"},
                    },
                    {
                        "type": "tool_use",
                        "id": "t3",
                        "name": "Bash",
                        "input": {"command": "pytest"},
                    },
                ]
            },
        },
    ]
    return tmp_jsonl(messages)
