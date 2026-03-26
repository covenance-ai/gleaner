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
import getpass
import gzip
import json
import os
import platform
import sys
import urllib.request
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"


def parse_transcript(path: Path) -> dict:
    """Parse a session JSONL file into summary metadata."""
    messages = []
    tool_uses = []
    first_ts = None
    last_ts = None

    with open(path) as f:
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

            msg_type = entry.get("type", "")
            if msg_type == "assistant":
                content = entry.get("message", {}).get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tool_uses.append(block.get("name", "unknown"))

    user_messages = [m for m in messages if m.get("type") == "user"]
    assistant_messages = [m for m in messages if m.get("type") == "assistant"]

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

    return {
        "message_count": len(messages),
        "user_message_count": len(user_messages),
        "assistant_message_count": len(assistant_messages),
        "tool_use_count": len(tool_uses),
        "tool_counts": tool_counts,
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
        "topic": topic,
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
    url_base = os.environ.get("GLEANER_URL", "")
    token = os.environ.get("GLEANER_TOKEN", "")

    raw = transcript_path.read_bytes()
    try:
        from gleaner_cli.scrub import scrub_text

        text = raw.decode("utf-8")
        scrubbed, stats = scrub_text(text)
        raw = scrubbed.encode("utf-8")
        if stats.redactions:
            metadata["redactions"] = stats.redactions
    except ImportError:
        pass  # scrubbing deps not installed — upload as-is
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
    if not os.environ.get("GLEANER_URL") or not os.environ.get("GLEANER_TOKEN"):
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
