#!/usr/bin/env python3
"""End-to-end integration test for the Gleaner pipeline.

Verifies the full upload-and-retrieve cycle:
  1. Creates a realistic JSONL transcript with user/assistant/tool messages
  2. Uploads it via gleaner_cli (simulating the SessionEnd hook)
  3. Retrieves metadata via GET /api/session/{id} and checks counts
  4. Retrieves the raw gzipped transcript via GET /api/session/{id}/raw,
     decompresses it, and verifies it matches the original content
  5. Optionally (--live) invokes the real `claude` CLI and checks that
     a new session appears on the server

Requires GLEANER_URL + GLEANER_TOKEN (env vars or ~/.config/gleaner.json).

Usage:
    pytest tests/test_e2e.py                  # via pytest
    python3 tests/test_e2e.py                 # upload + verify test
    python3 tests/test_e2e.py --live          # also run claude CLI smoke test
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
from gleaner_cli.config import get_credentials
from gleaner_cli.upload import parse_transcript, upload

GLEANER_URL, GLEANER_TOKEN = get_credentials()
REPO_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

passed = 0
failed = 0


def check(label: str, condition: bool, detail: str = ""):
    """Record and print a single pass/fail check."""
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        msg = f"  FAIL  {label}"
        if detail:
            msg += f"  -- {detail}"
        print(msg)


def api_get(path: str) -> Any:
    """GET a JSON endpoint from the Gleaner API. Returns parsed JSON."""
    url = f"{GLEANER_URL.rstrip('/')}{path}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {GLEANER_TOKEN}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def api_get_raw(path: str) -> bytes:
    """GET raw bytes from the Gleaner API."""
    url = f"{GLEANER_URL.rstrip('/')}{path}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {GLEANER_TOKEN}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


# ---------------------------------------------------------------------------
# Sample transcript builder
# ---------------------------------------------------------------------------


def build_sample_transcript() -> list[dict]:
    """Return a list of realistic JSONL entries mimicking a Claude Code session."""
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return [
        {
            "type": "summary",
            "timestamp": now_iso,
            "summary": "E2E test session",
        },
        {
            "type": "user",
            "timestamp": now_iso,
            "message": {
                "role": "user",
                "content": "List the Python files in this directory.",
            },
        },
        {
            "type": "assistant",
            "timestamp": now_iso,
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me check that for you."},
                    {
                        "type": "tool_use",
                        "id": "tu_001",
                        "name": "Bash",
                        "input": {"command": "ls *.py"},
                    },
                ],
            },
        },
        {
            "type": "tool_result",
            "timestamp": now_iso,
            "tool_use_id": "tu_001",
            "content": "server.py\ndb.py\n",
        },
        {
            "type": "assistant",
            "timestamp": now_iso,
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "I found two Python files: server.py and db.py.",
                    },
                    {
                        "type": "tool_use",
                        "id": "tu_002",
                        "name": "Read",
                        "input": {"file_path": "/tmp/server.py"},
                    },
                ],
            },
        },
        {
            "type": "tool_result",
            "timestamp": now_iso,
            "tool_use_id": "tu_002",
            "content": "# contents of server.py\n",
        },
        {
            "type": "user",
            "timestamp": now_iso,
            "message": {
                "role": "user",
                "content": "Thanks, that's all I needed.",
            },
        },
        {
            "type": "assistant",
            "timestamp": now_iso,
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "You're welcome!"},
                ],
            },
        },
    ]


# ---------------------------------------------------------------------------
# Test: upload + verify
# ---------------------------------------------------------------------------


def test_upload_and_verify():
    """Upload a sample transcript and verify metadata + raw roundtrip."""
    session_id = f"test_{int(time.time())}_{os.getpid()}"
    print(f"\n=== Upload & Verify Test (session_id={session_id}) ===\n")

    # -- Build JSONL file in a temp directory --
    entries = build_sample_transcript()
    tmpdir = tempfile.mkdtemp(prefix="gleaner_e2e_")
    transcript_path = Path(tmpdir) / f"{session_id}.jsonl"
    transcript_path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

    # -- Parse locally (same function the hook uses) --
    local_meta = parse_transcript(transcript_path)
    local_meta["session_id"] = session_id
    local_meta["cwd"] = "/tmp/gleaner-e2e-test"
    local_meta["project"] = "gleaner-e2e"

    check(
        "parse_transcript message_count",
        local_meta["message_count"] == len(entries),
        f"expected {len(entries)}, got {local_meta['message_count']}",
    )
    check(
        "parse_transcript user_message_count",
        local_meta["user_message_count"] == 2,
        f"expected 2, got {local_meta['user_message_count']}",
    )
    check(
        "parse_transcript assistant_message_count",
        local_meta["assistant_message_count"] == 3,
        f"expected 3, got {local_meta['assistant_message_count']}",
    )
    check(
        "parse_transcript tool_use_count",
        local_meta["tool_use_count"] == 2,
        f"expected 2, got {local_meta['tool_use_count']}",
    )
    check(
        "parse_transcript tool_counts",
        local_meta["tool_counts"] == {"Bash": 1, "Read": 1},
        f"got {local_meta['tool_counts']}",
    )

    # -- Upload via library function --
    try:
        upload(session_id, local_meta, transcript_path)
        check("upload succeeded", True)
    except Exception as exc:
        check("upload succeeded", False, str(exc))
        # Clean up and abort remaining checks -- server verification is pointless.
        shutil.rmtree(tmpdir, ignore_errors=True)
        return

    # -- Verify metadata via API --
    try:
        session_data = api_get(f"/api/session/{session_id}")
        check("GET /api/session/{id} returned data", True)

        meta = session_data.get("metadata", session_data)
        check(
            "metadata message_count matches",
            meta.get("message_count") == local_meta["message_count"],
            f"server={meta.get('message_count')}, local={local_meta['message_count']}",
        )
        check(
            "metadata user_message_count matches",
            meta.get("user_message_count") == local_meta["user_message_count"],
            f"server={meta.get('user_message_count')}, local={local_meta['user_message_count']}",
        )
        check(
            "metadata assistant_message_count matches",
            meta.get("assistant_message_count")
            == local_meta["assistant_message_count"],
            f"server={meta.get('assistant_message_count')}, local={local_meta['assistant_message_count']}",
        )
        check(
            "metadata tool_use_count matches",
            meta.get("tool_use_count") == local_meta["tool_use_count"],
            f"server={meta.get('tool_use_count')}, local={local_meta['tool_use_count']}",
        )
        check(
            "metadata tool_counts matches",
            meta.get("tool_counts") == local_meta["tool_counts"],
            f"server={meta.get('tool_counts')}",
        )
        check(
            "metadata session_id matches",
            meta.get("session_id") == session_id,
            f"server={meta.get('session_id')}",
        )
        check(
            "metadata project matches",
            meta.get("project") == "gleaner-e2e",
            f"server={meta.get('project')}",
        )
    except Exception as exc:
        check("GET /api/session/{id} returned data", False, str(exc))

    # -- Verify raw transcript roundtrip --
    try:
        raw_gz = api_get_raw(f"/api/session/{session_id}/raw")
        check("GET /api/session/{id}/raw returned data", len(raw_gz) > 0)

        raw_text = gzip.decompress(raw_gz).decode("utf-8")
        # Re-parse the downloaded JSONL and compare to the original entries
        downloaded_entries = [
            json.loads(line) for line in raw_text.strip().splitlines() if line.strip()
        ]
        check(
            "raw transcript entry count matches",
            len(downloaded_entries) == len(entries),
            f"downloaded={len(downloaded_entries)}, original={len(entries)}",
        )

        # Spot-check: first user message text survives the roundtrip
        original_first_user = entries[1]["message"]["content"]
        downloaded_first_user = (
            downloaded_entries[1].get("message", {}).get("content", "")
        )
        check(
            "raw transcript content matches (first user message)",
            downloaded_first_user == original_first_user,
            f"downloaded={downloaded_first_user!r}",
        )

        # Spot-check: tool_use block name survives
        downloaded_tool_name = None
        for block in downloaded_entries[2].get("message", {}).get("content", []):
            if isinstance(block, dict) and block.get("type") == "tool_use":
                downloaded_tool_name = block.get("name")
                break
        check(
            "raw transcript content matches (tool_use name)",
            downloaded_tool_name == "Bash",
            f"downloaded={downloaded_tool_name!r}",
        )
    except Exception as exc:
        check("GET /api/session/{id}/raw returned data", False, str(exc))

    # -- Cleanup --
    shutil.rmtree(tmpdir, ignore_errors=True)
    print(
        f"\n  NOTE: Test session '{session_id}' remains on the server (no delete endpoint)."
    )


# ---------------------------------------------------------------------------
# Test: live claude CLI invocation (--live flag)
# ---------------------------------------------------------------------------


def test_live_claude():
    """Run the real claude CLI with the gleaner plugin and verify a session appears."""
    print("\n=== Live Claude CLI Test ===\n")

    claude_bin = shutil.which("claude")
    if not claude_bin:
        check("claude CLI found", False, "'claude' not on PATH")
        return

    check("claude CLI found", True, claude_bin)

    # Fetch session IDs *before* running claude, so we can detect the new one.
    try:
        before = set(api_get("/api/sessions?ids_only=true").get("session_ids", []))
    except Exception as exc:
        check("pre-fetch session list", False, str(exc))
        return
    check("pre-fetch session list", True, f"{len(before)} existing sessions")

    # Run claude (assumes gleaner hook is installed via `gleaner setup`)
    cmd = [
        claude_bin,
        "-p",
        "Say exactly: gleaner e2e test ping",
        "--no-input",
    ]
    print(f"  Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        check(
            "claude exited successfully",
            result.returncode == 0,
            f"returncode={result.returncode}, stderr={result.stderr[:200]}",
        )
    except subprocess.TimeoutExpired:
        check("claude exited successfully", False, "timed out after 120s")
        return
    except Exception as exc:
        check("claude exited successfully", False, str(exc))
        return

    # The SessionEnd hook fires asynchronously -- give it a moment.
    time.sleep(5)

    # Fetch session IDs *after* and find the new one(s).
    try:
        after = set(api_get("/api/sessions?ids_only=true").get("session_ids", []))
    except Exception as exc:
        check("post-fetch session list", False, str(exc))
        return

    new_sessions = after - before
    check(
        "new session appeared on server",
        len(new_sessions) >= 1,
        f"new sessions: {new_sessions or 'none'}",
    )

    if new_sessions:
        new_id = next(iter(new_sessions))
        try:
            meta = api_get(f"/api/session/{new_id}")
            check(
                "new session has metadata",
                meta.get("metadata", {}).get("message_count", 0) > 0
                or meta.get("message_count", 0) > 0,
                f"session data keys: {list(meta.keys())}",
            )
        except Exception as exc:
            check("new session has metadata", False, str(exc))

        print(f"\n  NOTE: Live test session '{new_id}' remains on the server.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    global passed, failed

    parser = argparse.ArgumentParser(description="Gleaner end-to-end integration test")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Also run the full claude CLI invocation test",
    )
    args = parser.parse_args()

    # Pre-flight checks
    if not GLEANER_URL:
        print("ERROR: GLEANER_URL environment variable is not set.")
        sys.exit(1)
    if not GLEANER_TOKEN:
        print("ERROR: GLEANER_TOKEN environment variable is not set.")
        sys.exit(1)

    print(f"Gleaner URL: {GLEANER_URL}")
    print(f"Token:       {GLEANER_TOKEN[:8]}...")

    # Sanity: make sure the server is reachable
    try:
        health = api_get("/api/health")
        check("server health check", health.get("status") == "ok", f"response={health}")
    except Exception as exc:
        print(f"\n  FAIL  Cannot reach Gleaner server: {exc}")
        sys.exit(1)

    test_upload_and_verify()

    if args.live:
        test_live_claude()
    else:
        print("\n  SKIP  Live claude CLI test (pass --live to enable)")

    # Summary
    total = passed + failed
    print(f"\n{'=' * 50}")
    print(f"Results: {passed}/{total} passed, {failed}/{total} failed")
    print(f"{'=' * 50}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
