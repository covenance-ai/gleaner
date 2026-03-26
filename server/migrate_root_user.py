"""One-time migration: reassign sessions from 'root' to 'ikamen'.

The VPS ran Claude Code as root, so ~6.9k sessions have provenance.user='root'.
These are all ikamen's sessions.

Usage: python migrate_root_user.py [--dry-run]
"""

import sys
from google.cloud import firestore

PROJECT = "covenance-469421"


def migrate(dry_run: bool = False):
    db = firestore.Client(project=PROJECT)
    batch = db.batch()
    count = 0

    for doc in db.collection("sessions").where("provenance.user", "==", "root").stream():
        batch.update(doc.reference, {"provenance.user": "ikamen"})
        count += 1
        if count % 500 == 0:
            if not dry_run:
                batch.commit()
                batch = db.batch()
            print(f"  {count} sessions processed...")

    if count % 500 != 0 and not dry_run:
        batch.commit()

    print(f"{'[DRY RUN] ' if dry_run else ''}Done. {'Would update' if dry_run else 'Updated'} {count} sessions.")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    migrate(dry_run=dry)
