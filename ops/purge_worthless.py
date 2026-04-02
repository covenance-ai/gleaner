"""Delete worthless sessions (rate-limited, empty) from Firestore + GCS.

Scans all sessions, downloads their transcripts to check for rate-limit
messages, and deletes matching sessions. Run backfill_counters.py after
to rebuild the counters.

Usage:
    python ops/purge_worthless.py --dry-run   # show what would be deleted
    python ops/purge_worthless.py             # delete them
"""

import argparse
import gzip
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
import db


def is_worthless_transcript(transcript_gz: bytes) -> str | None:
    """Check if a transcript is worthless. Returns reason string or None.

    Worthless = no human intent (no user messages). Sessions with user
    messages are kept even if rate-limited or missing assistant responses.
    """
    try:
        raw = gzip.decompress(transcript_gz).decode("utf-8")
    except Exception:
        return "corrupt"

    entries = []
    for line in raw.strip().split("\n"):
        if line.strip():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    has_user = any(
        (e.get("type") or e.get("role")) == "user" for e in entries
    )
    if not has_user:
        return "no_user_messages"
    return None


def scan_and_purge(dry_run: bool = False, workers: int = 6):
    print("Scanning all sessions...", flush=True)
    sessions = []
    for doc in db._db().collection("sessions").stream():
        sessions.append(doc.id)

    print(f"Found {len(sessions)} sessions, checking transcripts...")

    to_delete: list[tuple[str, str]] = []  # (session_id, reason)
    checked = 0
    errors = 0

    def check_one(sid):
        gz = db.get_session_transcript(sid)
        if gz is None:
            return sid, "no_transcript"
        reason = is_worthless_transcript(gz)
        return sid, reason

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(check_one, sid): sid for sid in sessions}
        for future in as_completed(futures):
            checked += 1
            try:
                sid, reason = future.result()
                if reason:
                    to_delete.append((sid, reason))
            except Exception as e:
                errors += 1
            if checked % 200 == 0:
                print(f"  checked {checked}/{len(sessions)}, found {len(to_delete)} worthless...", flush=True)

    # Summary by reason
    from collections import Counter
    reasons = Counter(r for _, r in to_delete)
    print(f"\nWorthless sessions: {len(to_delete)} / {len(sessions)}")
    for reason, count in reasons.most_common():
        print(f"  {reason}: {count}")

    if dry_run:
        print(f"\n[DRY RUN] Would delete {len(to_delete)} sessions")
        return

    print(f"\nDeleting {len(to_delete)} sessions...")
    deleted = 0
    for i, (sid, reason) in enumerate(to_delete, 1):
        try:
            db.delete_session(sid)
            deleted += 1
        except Exception as e:
            print(f"  {sid}: delete failed: {e}", file=sys.stderr)
        if i % 100 == 0:
            print(f"  deleted {i}/{len(to_delete)}...", flush=True)

    print(f"\nDeleted {deleted} sessions. Run backfill_counters.py to rebuild counters.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Purge worthless sessions from cloud")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted")
    parser.add_argument("-j", "--workers", type=int, default=6, help="Parallel workers")
    args = parser.parse_args()
    scan_and_purge(dry_run=args.dry_run, workers=args.workers)
