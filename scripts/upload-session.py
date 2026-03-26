#!/usr/bin/env python3
"""Gleaner SessionEnd hook: uploads the completed session transcript to central storage.

Reads session info from stdin (Claude Code hook JSON), finds the JSONL transcript
on disk, parses metadata, and uploads to the Gleaner API. Best-effort: never fails
loudly, never blocks Claude Code.

Config via environment variables:
    GLEANER_URL   - Base URL of the Gleaner API
    GLEANER_TOKEN - Bearer token for authentication
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from upload_session_lib import parse_transcript, upload

GLEANER_URL = os.environ.get("GLEANER_URL", "")
GLEANER_TOKEN = os.environ.get("GLEANER_TOKEN", "")
CLAUDE_DIR = Path.home() / ".claude"


def find_session_file(session_id: str) -> Path | None:
    """Find the JSONL transcript for a session ID."""
    projects_dir = CLAUDE_DIR / "projects"
    if not projects_dir.exists():
        return None
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        candidate = project_dir / f"{session_id}.jsonl"
        if candidate.exists():
            return candidate
    return None


def main():
    if not GLEANER_URL or not GLEANER_TOKEN:
        return

    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        return

    session_id = hook_input.get("session_id", "")
    cwd = hook_input.get("cwd", "")
    if not session_id:
        return

    transcript_path = find_session_file(session_id)
    if not transcript_path:
        return

    metadata = parse_transcript(transcript_path)
    metadata["cwd"] = cwd
    metadata["session_id"] = session_id
    metadata["project"] = transcript_path.parent.name

    upload(session_id, metadata, transcript_path)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
