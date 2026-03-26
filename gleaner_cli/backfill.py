"""Upload existing Claude Code session transcripts to Gleaner.

Scans ~/.claude/projects/ for JSONL session files and uploads any that
haven't been uploaded yet (checks with the server first).

Usage:
    gleaner-backfill                  # upload all sessions
    gleaner-backfill --dry-run        # just list what would be uploaded
    gleaner-backfill --project foo    # only sessions from project "foo"

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

from gleaner_cli.upload import collect_provenance, parse_transcript, upload

CLAUDE_DIR = Path.home() / ".claude"


def get_existing_session_ids() -> set[str]:
    """Fetch session IDs already on the server."""
    url = os.environ.get("GLEANER_URL", "")
    token = os.environ.get("GLEANER_TOKEN", "")
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
    """Find all session JSONL files. Returns [(session_id, project, path), ...]."""
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


def main():
    parser = argparse.ArgumentParser(
        description="Upload existing Claude Code sessions to Gleaner"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="List sessions without uploading"
    )
    parser.add_argument(
        "--project", type=str, help="Filter by project name (substring match)"
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-upload even if already on server"
    )
    args = parser.parse_args()

    if not os.environ.get("GLEANER_URL") or not os.environ.get("GLEANER_TOKEN"):
        print("Error: GLEANER_URL and GLEANER_TOKEN must be set", file=sys.stderr)
        sys.exit(1)

    sessions = find_all_sessions(args.project)
    print(f"Found {len(sessions)} session(s) on disk")

    if not args.force:
        existing = get_existing_session_ids()
        sessions = [
            (sid, proj, path) for sid, proj, path in sessions if sid not in existing
        ]
        print(f"{len(sessions)} new session(s) to upload")

    if args.dry_run:
        for sid, proj, path in sessions:
            size_kb = path.stat().st_size / 1024
            print(f"  {sid[:12]}...  {proj}  ({size_kb:.0f} KB)")
        return

    success = 0
    failed = 0
    for i, (sid, proj, path) in enumerate(sessions, 1):
        try:
            metadata = parse_transcript(path)
            metadata["cwd"] = ""
            metadata["session_id"] = sid
            metadata["project"] = proj
            upload(sid, metadata, path)
            success += 1
            print(f"  [{i}/{len(sessions)}] {sid[:12]}... uploaded")
        except Exception as e:
            failed += 1
            print(f"  [{i}/{len(sessions)}] {sid[:12]}... FAILED: {e}")

    print(f"\nDone: {success} uploaded, {failed} failed")


if __name__ == "__main__":
    main()
