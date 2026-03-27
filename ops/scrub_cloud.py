#!/usr/bin/env python3
"""One-time scrub of all existing transcripts in GCS.

Downloads each gzipped JSONL from gs://gleaner-sessions/sessions/,
scrubs PII and secrets, re-uploads, and updates Firestore metadata.
Produces a JSON report with per-session and aggregate stats.

Usage:
    python3 ops/scrub_cloud.py              # scrub all transcripts
    python3 ops/scrub_cloud.py --dry-run    # show what would be scrubbed
    python3 ops/scrub_cloud.py --workers 8  # parallel workers (default: 6)
"""

from __future__ import annotations

import gzip
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from gleaner_cli.scrub import scrub_text

GCP_PROJECT = "covenance-469421"
GCS_BUCKET = "gleaner-sessions"
REPORT_PATH = Path(__file__).parent / "scrub_report.json"

_lock = threading.Lock()
_results: list[dict] = []


def process_blob(blob, total, idx, dry_run, bucket, db):
    name = blob.name
    if not name.endswith(".jsonl.gz"):
        return

    session_id = name.removeprefix("sessions/").removesuffix(".jsonl.gz")
    tag = f"[{idx}/{total}] {session_id[:16]}..."

    # Check if already scrubbed (has redactions field in Firestore)
    try:
        doc_ref = db.collection("sessions").document(session_id)
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict() or {}
            if "redactions" in data:
                with _lock:
                    _results.append(
                        {
                            "session_id": session_id,
                            "status": "already_scrubbed",
                            "redactions": data["redactions"],
                        }
                    )
                return
    except Exception:
        pass  # proceed with scrubbing if Firestore check fails

    try:
        gz_data = blob.download_as_bytes()
    except Exception as e:
        print(f"  {tag} FAIL (download: {e})")
        with _lock:
            _results.append(
                {"session_id": session_id, "status": "error", "error": str(e)}
            )
        return

    try:
        text = gzip.decompress(gz_data).decode("utf-8")
    except Exception as e:
        print(f"  {tag} SKIP (decompress: {e})")
        with _lock:
            _results.append(
                {"session_id": session_id, "status": "error", "error": str(e)}
            )
        return

    scrubbed, stats = scrub_text(text)

    if stats.redactions == 0:
        # Mark as scrubbed with 0 so we don't re-process
        if not dry_run:
            try:
                doc_ref = db.collection("sessions").document(session_id)
                doc = doc_ref.get()
                if doc.exists:
                    doc_ref.update({"redactions": 0})
            except Exception:
                pass
        with _lock:
            _results.append(
                {"session_id": session_id, "status": "clean", "redactions": 0}
            )
        return

    if dry_run:
        print(f"  {tag} WOULD scrub ({stats.redactions} redaction(s))")
        with _lock:
            _results.append(
                {
                    "session_id": session_id,
                    "status": "would_scrub",
                    "redactions": stats.redactions,
                }
            )
        return

    # Re-upload scrubbed transcript
    scrubbed_bytes = scrubbed.encode("utf-8")
    new_gz = gzip.compress(scrubbed_bytes)
    blob.upload_from_string(new_gz, content_type="application/gzip")

    # Update Firestore metadata
    try:
        doc_ref = db.collection("sessions").document(session_id)
        doc = doc_ref.get()
        if doc.exists:
            doc_ref.update(
                {
                    "redactions": stats.redactions,
                    "transcript_size": len(scrubbed_bytes),
                    "transcript_gz_size": len(new_gz),
                }
            )
    except Exception:
        pass

    with _lock:
        _results.append(
            {
                "session_id": session_id,
                "status": "scrubbed",
                "redactions": stats.redactions,
            }
        )
    print(f"  {tag} scrubbed ({stats.redactions} redaction(s))")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Scrub all existing Gleaner transcripts in GCS"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be scrubbed without modifying",
    )
    parser.add_argument(
        "--workers", type=int, default=6, help="Number of parallel workers (default: 6)"
    )
    args = parser.parse_args()

    from google.cloud import firestore, storage

    gcs = storage.Client(project=GCP_PROJECT)
    bucket = gcs.bucket(GCS_BUCKET)
    db = firestore.Client(project=GCP_PROJECT)

    blobs = [
        b for b in bucket.list_blobs(prefix="sessions/") if b.name.endswith(".jsonl.gz")
    ]
    total = len(blobs)
    t0 = time.time()
    print(f"Found {total} transcript(s) in gs://{GCS_BUCKET}/sessions/")
    print(f"Using {args.workers} workers\n")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(process_blob, blob, total, i, args.dry_run, bucket, db): blob
            for i, blob in enumerate(blobs, 1)
        }
        for future in as_completed(futures):
            exc = future.exception()
            if exc:
                blob = futures[future]
                print(f"  ERROR processing {blob.name}: {exc}")

    elapsed = time.time() - t0

    # Build report
    by_status = {}
    total_redactions = 0
    for r in _results:
        status = r["status"]
        by_status.setdefault(status, []).append(r)
        total_redactions += r.get("redactions", 0)

    report = {
        "total_transcripts": total,
        "elapsed_seconds": round(elapsed, 1),
        "total_redactions": total_redactions,
        "summary": {status: len(items) for status, items in sorted(by_status.items())},
        "sessions": sorted(_results, key=lambda r: r["session_id"]),
    }

    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print()
    print(f"Completed in {elapsed:.0f}s")
    print(f"Total redactions: {total_redactions}")
    for status, items in sorted(by_status.items()):
        print(f"  {status}: {len(items)}")
    print(f"\nFull report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
