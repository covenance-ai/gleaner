"""Add source/task_type tags to existing sessions in Firestore.

Reads metadata already in Firestore (project, topic, provenance.host, cwd)
and writes back computed tags. No transcript downloads needed.

Usage:
    python ops/backfill_tags.py --dry-run   # show what would change
    python ops/backfill_tags.py             # update Firestore
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import db
from gleaner.tags import tag_session


def run(dry_run: bool = False):
    print("Scanning sessions...", flush=True)
    docs = list(db._db().collection("sessions").stream())
    print(f"Found {len(docs)} sessions")

    updates = 0
    unchanged = 0
    tag_counts: Counter = Counter()

    for i, doc in enumerate(docs, 1):
        data = doc.to_dict() or {}
        prov = data.get("provenance", {})
        tags = tag_session(
            project=data.get("project", ""),
            topic=data.get("topic", ""),
            host=prov.get("host", ""),
            cwd=data.get("cwd", ""),
        )

        # Skip if tags already match
        if data.get("source") == tags["source"] and data.get("task_type") == tags["task_type"]:
            unchanged += 1
            tag_counts[(tags["source"], tags["task_type"])] += 1
            continue

        tag_counts[(tags["source"], tags["task_type"])] += 1
        updates += 1

        if not dry_run:
            doc.reference.update(tags)

        if i % 500 == 0:
            print(f"  [{i}/{len(docs)}] {updates} to update...", flush=True)

    print(f"\n{'Would update' if dry_run else 'Updated'}: {updates}, already correct: {unchanged}")
    print("\nTag distribution:")
    for (src, tt), count in tag_counts.most_common():
        print(f"  {src:>10} / {tt:<20}: {count:>5}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill source/task_type tags")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
