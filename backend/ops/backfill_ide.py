"""Set ide='claude_code' on all existing sessions that lack the field.

All sessions uploaded before Cursor support are Claude Code sessions.
Run this before any Cursor backfill to avoid ambiguity.

Usage:
    python ops/backfill_ide.py --dry-run   # show what would change
    python ops/backfill_ide.py             # update Firestore
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import db


def run(dry_run: bool = False):
    print("Scanning sessions...", flush=True)
    docs = list(db._db().collection("sessions").stream())
    print(f"Found {len(docs)} sessions")

    needs_update = 0
    already_set = 0

    for i, doc in enumerate(docs, 1):
        data = doc.to_dict() or {}
        if data.get("ide"):
            already_set += 1
            continue

        needs_update += 1
        if not dry_run:
            doc.reference.update({"ide": "claude_code"})

        if i % 500 == 0:
            print(f"  [{i}/{len(docs)}] ...", flush=True)

    action = "Would update" if dry_run else "Updated"
    print(f"\n{action}: {needs_update}, already set: {already_set}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill ide field on existing sessions")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
