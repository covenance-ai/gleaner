"""Cursor session discovery.

Scans ~/.cursor/projects/*/agent-transcripts/ for session JSONL files.
These are written by Cursor's agent mode and have a compatible format
with Claude Code transcripts (role-based instead of type-based messages).

Project directory names use dashes instead of path separators, e.g.
"Users-ikamen-ai-workspace-ilya-kodo" for /Users/ikamen/ai-workspace/ilya/kodo.
This encoding is ambiguous (dashes in original paths) so we keep the
Cursor project name as-is for identification.
"""

from pathlib import Path

CURSOR_DIR = Path.home() / ".cursor"


def find_all_cursor_sessions(
    project_filter: str | None = None,
) -> list[tuple[str, str, Path]]:
    """Find all Cursor agent-transcript JSONL files.

    Returns [(session_id, project_name, path), ...] in the same shape
    as backfill.find_all_sessions for Claude Code.
    """
    projects_dir = CURSOR_DIR / "projects"
    if not projects_dir.exists():
        return []

    sessions = []
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        project_name = project_dir.name
        if project_filter and project_filter not in project_name:
            continue

        transcripts_dir = project_dir / "agent-transcripts"
        if not transcripts_dir.is_dir():
            continue

        for session_dir in sorted(transcripts_dir.iterdir()):
            if not session_dir.is_dir():
                continue
            session_id = session_dir.name
            jsonl = session_dir / f"{session_id}.jsonl"
            if jsonl.exists():
                sessions.append((session_id, project_name, jsonl))

    return sessions


def find_cursor_session_file(conversation_id: str) -> Path | None:
    """Find the JSONL transcript for a Cursor conversation ID.

    Searches ~/.cursor/projects/*/agent-transcripts/{id}/{id}.jsonl.
    """
    projects_dir = CURSOR_DIR / "projects"
    if not projects_dir.exists():
        return None
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        candidate = project_dir / "agent-transcripts" / conversation_id / f"{conversation_id}.jsonl"
        if candidate.exists():
            return candidate
    return None
