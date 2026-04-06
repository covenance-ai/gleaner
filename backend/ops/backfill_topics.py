#!/usr/bin/env python3
"""Backfill topic field for existing sessions in Firestore.

Downloads each transcript from GCS, extracts the first user message,
and updates the Firestore session document with a 'topic' field.
Skips sessions that already have a topic.

Usage:
    python3 ops/backfill_topics.py              # backfill all
    python3 ops/backfill_topics.py --dry-run    # show what would be updated
    python3 ops/backfill_topics.py --workers 8  # parallel workers
"""

from __future__ import annotations

import gzip
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

GCP_PROJECT = "covenance-469421"
GCS_BUCKET = "gleaner-sessions"

_lock = threading.Lock()
_updated = 0
_skipped = 0
_failed = 0


def extract_topic(text: str) -> str:
    """Extract first user message text from JSONL transcript."""
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "user":
            continue
        content = entry.get("message", {}).get("content", "")
        if isinstance(content, str):
            topic = content.strip()
        elif isinstance(content, list):
            topic = ""
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    topic = (block.get("text") or "").strip()
                    break
        else:
            continue
        if topic:
            if len(topic) > 200:
                topic = topic[:200] + "..."
            return topic
    return ""


def process_session(session_id, data, bucket, db, dry_run):
    global _updated, _skipped, _failed

    # Skip if topic already set
    if data.get("topic"):
        with _lock:
            _skipped += 1
        return

    # Download transcript
    blob = bucket.blob(f"sessions/{session_id}.jsonl.gz")
    try:
        gz_data = blob.download_as_bytes()
        text = gzip.decompress(gz_data).decode("utf-8")
    except Exception as e:
        with _lock:
            _failed += 1
        return

    topic = extract_topic(text)
    if not topic:
        with _lock:
            _skipped += 1
        return

    if dry_run:
        print(f"  {session_id[:16]}... -> {topic[:60]}")
        with _lock:
            _updated += 1
        return

    try:
        db.collection("sessions").document(session_id).update({"topic": topic})
        with _lock:
            _updated += 1
    except Exception:
        with _lock:
            _failed += 1


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Backfill topic field for Gleaner sessions")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    from google.cloud import firestore, storage

    db = firestore.Client(project=GCP_PROJECT)
    gcs = storage.Client(project=GCP_PROJECT)
    bucket = gcs.bucket(GCS_BUCKET)

    # Get all sessions
    sessions = []
    for doc in db.collection("sessions").stream():
        data = doc.to_dict() or {}
        sessions.append((doc.id, data))

    total = len(sessions)
    need_topic = sum(1 for _, d in sessions if not d.get("topic"))
    print(f"Found {total} sessions, {need_topic} need topic backfill")
    print(f"Using {args.workers} workers\n")

    t0 = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(process_session, sid, data, bucket, db, args.dry_run): sid
            for sid, data in sessions
        }
        for future in as_completed(futures):
            exc = future.exception()
            if exc:
                print(f"  ERROR: {exc}")

    elapsed = time.time() - t0
    action = "would update" if args.dry_run else "updated"
    print(f"\nDone in {elapsed:.0f}s: {action} {_updated}, skipped {_skipped}, failed {_failed}")


if __name__ == "__main__":
    main()
