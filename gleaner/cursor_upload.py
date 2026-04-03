"""Gleaner hook handler for Cursor's `stop` event.

Installed as the `gleaner-cursor-upload` command and registered in
~/.cursor/hooks.json under the `stop` hook. Cursor passes a JSON
payload on stdin with conversation_id, status, and workspace_roots.

Best-effort: never fails loudly, never blocks Cursor.
"""

import json
import os
import sys

from gleaner.config import get_credentials
from gleaner.cursor import find_cursor_session_file
from gleaner.tags import tag_session
from gleaner.upload import collect_provenance, parse_transcript, upload


def main():
    url, token = get_credentials()
    if not url or not token:
        return

    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        return

    conversation_id = hook_input.get("conversation_id", "")
    if not conversation_id:
        return

    status = hook_input.get("status", "completed")
    workspace_roots = hook_input.get("workspace_roots", [])
    cwd = workspace_roots[0] if workspace_roots else ""

    transcript_path = find_cursor_session_file(conversation_id)
    if not transcript_path:
        return

    metadata = parse_transcript(transcript_path)
    if metadata.pop("worthless", False):
        return

    metadata["cwd"] = cwd
    metadata["session_id"] = conversation_id
    metadata["project"] = transcript_path.parent.parent.parent.name

    provenance = collect_provenance()
    env_source = os.environ.get("CLAUDE_SESSION_SOURCE", "")
    tags = tag_session(
        metadata["project"], metadata.get("topic", ""), provenance["host"], cwd,
        ide="cursor",
    )
    metadata["source"] = env_source or tags["source"]
    metadata["task_type"] = tags["task_type"]
    metadata["ide"] = "cursor"
    metadata["aborted"] = status == "aborted"
    metadata["has_errors"] = status == "error"

    upload(conversation_id, metadata, transcript_path)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
