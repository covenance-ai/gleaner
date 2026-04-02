"""Gleaner session upload: hook handler and upload library.

Used as a Claude Code SessionEnd hook via the `gleaner-upload` command.
Reads session info from stdin (Claude Code hook JSON), finds the JSONL
transcript on disk, parses metadata, and uploads to the Gleaner API.

Best-effort: never fails loudly, never blocks Claude Code.

Config via environment variables:
    GLEANER_URL   - Base URL of the Gleaner API
    GLEANER_TOKEN - Bearer token for authentication
"""

import base64
import datetime
import getpass
import gzip
import json
import os
import platform
import sys
import urllib.request
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"


def _epoch_to_iso(epoch: float) -> str:
    """Convert a Unix epoch timestamp to ISO 8601 UTC string."""
    return datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc).isoformat()


def _entry_role(entry: dict) -> str:
    """Extract the role from a JSONL entry (Claude Code uses 'type', Cursor uses 'role')."""
    return entry.get("type") or entry.get("role") or ""


def parse_transcript(path: Path) -> dict:
    """Parse a session JSONL file into summary metadata.

    Handles both Claude Code format (type/timestamp fields) and
    Cursor agent-transcript format (role field, no timestamps).
    """
    messages = []
    tool_uses = []
    first_ts = None
    last_ts = None

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            messages.append(entry)
            ts = entry.get("timestamp")
            if ts:
                if first_ts is None:
                    first_ts = ts
                last_ts = ts

            if _entry_role(entry) == "assistant":
                content = entry.get("message", {}).get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tool_uses.append(block.get("name", "unknown"))

    user_messages = [m for m in messages if _entry_role(m) == "user"]
    assistant_messages = [m for m in messages if _entry_role(m) == "assistant"]

    tool_counts = {}
    for t in tool_uses:
        tool_counts[t] = tool_counts.get(t, 0) + 1

    # Extract first user message as session "topic"
    topic = ""
    for m in user_messages:
        content = m.get("message", {}).get("content", "")
        if isinstance(content, str):
            topic = content.strip()
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    topic = (block.get("text") or "").strip()
                    break
        if topic:
            break
    if len(topic) > 200:
        topic = topic[:200] + "..."

    # If no timestamps from the file content, fall back to file metadata
    if first_ts is None:
        stat = path.stat()
        # Use birthtime if available (macOS), otherwise mtime
        ctime = getattr(stat, "st_birthtime", stat.st_mtime)
        first_ts = _epoch_to_iso(ctime)
        last_ts = _epoch_to_iso(stat.st_mtime)

    # Worthless = no human intent at all (no user messages).
    # Sessions with user messages are always worth keeping, even if
    # rate-limited or missing assistant responses.
    worthless = not user_messages

    return {
        "message_count": len(messages),
        "user_message_count": len(user_messages),
        "assistant_message_count": len(assistant_messages),
        "tool_use_count": len(tool_uses),
        "tool_counts": tool_counts,
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
        "topic": topic,
        "worthless": worthless,
    }


def collect_provenance() -> dict:
    """Auto-collect uploader info."""
    return {
        "user": getpass.getuser(),
        "host": platform.node(),
        "platform": f"{platform.system()} {platform.machine()}",
    }


def upload(session_id: str, metadata: dict, transcript_path: Path):
    """Upload session metadata + gzipped transcript to the Gleaner API."""
    from gleaner.config import get_credentials

    url_base, token = get_credentials()

    raw = transcript_path.read_bytes()
    from gleaner.scrub import scrub_text

    text = raw.decode("utf-8")
    scrubbed, stats = scrub_text(text)
    raw = scrubbed.encode("utf-8")
    if stats.redactions:
        metadata["redactions"] = stats.redactions
    compressed = gzip.compress(raw)

    payload = {
        "session_id": session_id,
        "metadata": metadata,
        "provenance": collect_provenance(),
        "transcript_size": len(raw),
        "transcript_gz_b64": base64.b64encode(compressed).decode(),
    }

    body = json.dumps(payload).encode()
    url = f"{url_base.rstrip('/')}/api/session"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    urllib.request.urlopen(req, timeout=30)


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
    """Entry point for gleaner-upload CLI and SessionEnd hook."""
    from gleaner.config import get_credentials

    url, token = get_credentials()
    if not url or not token:
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
    if metadata.pop("worthless", False):
        return

    metadata["cwd"] = cwd
    metadata["session_id"] = session_id
    metadata["project"] = transcript_path.parent.name

    from gleaner.tags import tag_session

    provenance = collect_provenance()
    # Prefer explicit env var (set by orchestrators like kodo) over heuristics
    env_source = os.environ.get("CLAUDE_SESSION_SOURCE", "")
    tags = tag_session(metadata["project"], metadata.get("topic", ""), provenance["host"], cwd)
    metadata["source"] = env_source or tags["source"]
    metadata["task_type"] = tags["task_type"]
    metadata["ide"] = "claude_code"
    metadata["aborted"] = False
    metadata["has_errors"] = False

    status_file = Path(f"/tmp/gleaner_upload_{session_id}")
    try:
        upload(session_id, metadata, transcript_path)
        status_file.write_text("ok")
    except Exception as exc:
        status_file.write_text(str(exc))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
