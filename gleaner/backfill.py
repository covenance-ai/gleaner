"""Upload existing session transcripts to Gleaner.

Supports both Claude Code (~/.claude/projects/) and Cursor
(~/.cursor/projects/agent-transcripts/) sessions through a
unified pipeline.

Usage:
    gleaner backfill                          # Claude Code (default)
    gleaner backfill --source cursor          # Cursor sessions
    gleaner backfill --source cursor --dry-run
    gleaner backfill --project foo            # filter by project name

Config via environment variables:
    GLEANER_URL   - Base URL of the Gleaner API
    GLEANER_TOKEN - Bearer token for authentication
"""

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

from gleaner.config import get_credentials
from gleaner.cursor import find_all_cursor_sessions
from gleaner.tags import tag_session
from gleaner.upload import collect_provenance, parse_transcript, upload

CLAUDE_DIR = Path.home() / ".claude"


def get_existing_session_ids() -> set[str]:
    """Fetch session IDs already on the server."""
    url, token = get_credentials()
    if not url or not token:
        return set()
    try:
        req_url = f"{url.rstrip('/')}/api/sessions?ids_only=true"
        req = urllib.request.Request(req_url)
        req.add_header("Authorization", f"Bearer {token}")
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read())
        return set(data.get("session_ids", []))
    except Exception:
        return set()


def find_all_sessions(project_filter: str | None = None) -> list[tuple[str, str, Path]]:
    """Find all Claude Code session JSONL files.

    Returns [(session_id, project, path), ...].
    """
    projects_dir = CLAUDE_DIR / "projects"
    if not projects_dir.exists():
        return []

    sessions = []
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        project_name = project_dir.name
        if project_filter and project_filter not in project_name:
            continue
        for jsonl in sorted(project_dir.glob("*.jsonl")):
            session_id = jsonl.stem
            sessions.append((session_id, project_name, jsonl))
    return sessions


def run(
    dry_run: bool = False,
    project: str | None = None,
    force: bool = False,
    source: str = "claude",
):
    """Run the backfill for the given source."""
    url, token = get_credentials()
    if not url or not token:
        print("Error: not configured. Run 'gleaner setup URL TOKEN' first.", file=sys.stderr)
        sys.exit(1)

    ide = "cursor" if source == "cursor" else "claude_code"

    if source == "cursor":
        sessions = find_all_cursor_sessions(project)
    else:
        sessions = find_all_sessions(project)

    print(f"Found {len(sessions)} {source} session(s) on disk")

    if not force:
        existing = get_existing_session_ids()
        sessions = [
            (sid, proj, path) for sid, proj, path in sessions if sid not in existing
        ]
        print(f"{len(sessions)} new session(s) to upload")

    if dry_run:
        for sid, proj, path in sessions:
            size_kb = path.stat().st_size / 1024
            print(f"  {sid[:12]}...  {proj}  ({size_kb:.0f} KB)")
        return

    success = 0
    failed = 0
    skipped = 0
    for i, (sid, proj, path) in enumerate(sessions, 1):
        try:
            metadata = parse_transcript(path)
            if metadata.pop("worthless", False):
                skipped += 1
                continue
            metadata["cwd"] = ""
            metadata["session_id"] = sid
            metadata["project"] = proj
            provenance = collect_provenance()
            tags = tag_session(proj, metadata.get("topic", ""), provenance["host"], "", ide=ide)
            metadata["source"] = tags["source"]
            metadata["task_type"] = tags["task_type"]
            metadata["ide"] = ide
            metadata["aborted"] = False
            metadata["has_errors"] = False
            upload(sid, metadata, path)
            success += 1
            print(f"  [{i}/{len(sessions)}] {sid[:12]}... uploaded")
        except Exception as e:
            failed += 1
            print(f"  [{i}/{len(sessions)}] {sid[:12]}... FAILED: {e}")

    print(f"\nDone: {success} uploaded, {skipped} skipped (worthless), {failed} failed")


def main():
    parser = argparse.ArgumentParser(
        description="Upload existing sessions to Gleaner"
    )
    parser.add_argument("--dry-run", action="store_true", help="List without uploading")
    parser.add_argument("--project", type=str, help="Filter by project name")
    parser.add_argument("--force", action="store_true", help="Re-upload existing")
    parser.add_argument(
        "--source",
        choices=["claude", "cursor"],
        default="claude",
        help="Session source (default: claude)",
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run, project=args.project, force=args.force, source=args.source)


if __name__ == "__main__":
    main()
