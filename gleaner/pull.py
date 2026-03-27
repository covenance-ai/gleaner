"""Download Gleaner sessions for local analysis.

Syncs session metadata to a local Parquet file and optionally downloads
raw transcripts as .jsonl.gz files. Uses caching: only fetches sessions
newer than the latest local data, and skips already-downloaded transcripts.

Local data directory (~/.gleaner/ by default):
  sessions.parquet  — structured metadata, one row per session
  transcripts/      — raw session transcripts ({session_id}.jsonl.gz)

Usage:
    gleaner pull                    # sync metadata to Parquet
    gleaner pull --transcripts      # also download raw transcripts
    gleaner pull -j8 --transcripts  # 8 parallel transcript downloads
    gleaner pull -o ./data          # custom output directory

Requires pyarrow: pip install 'gleaner-cli[pull]'
"""

import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from gleaner.config import get_credentials

DEFAULT_DATA_DIR = Path.home() / ".gleaner"


def _api_get(url: str, token: str, path: str, params: dict | None = None) -> bytes:
    from urllib.parse import urlencode

    full_url = f"{url.rstrip('/')}{path}"
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            full_url += f"?{urlencode(clean)}"
    req = urllib.request.Request(full_url)
    req.add_header("Authorization", f"Bearer {token}")
    return urllib.request.urlopen(req, timeout=60).read()


def _fetch_sessions(url: str, token: str, since: str | None = None) -> list[dict]:
    params = {"limit": "100000", "export": "true"}
    if since:
        params["since"] = since
    data = json.loads(_api_get(url, token, "/api/sessions", params))
    return data.get("sessions", [])


def _flatten_session(s: dict) -> dict:
    """Flatten nested session dict into a tabular row."""
    prov = s.get("provenance", {})
    uploaded_at = s.get("uploaded_at", "")
    if hasattr(uploaded_at, "isoformat"):
        uploaded_at = uploaded_at.isoformat()
    return {
        "session_id": s.get("session_id", ""),
        "user": prov.get("user", ""),
        "host": prov.get("host", ""),
        "platform": prov.get("platform", ""),
        "project": s.get("project", ""),
        "topic": s.get("topic", ""),
        "cwd": s.get("cwd", ""),
        "message_count": s.get("message_count", 0),
        "user_message_count": s.get("user_message_count", 0),
        "assistant_message_count": s.get("assistant_message_count", 0),
        "tool_use_count": s.get("tool_use_count", 0),
        "tool_counts_json": json.dumps(s.get("tool_counts", {})),
        "first_timestamp": s.get("first_timestamp", ""),
        "last_timestamp": s.get("last_timestamp", ""),
        "transcript_size": s.get("transcript_size", 0),
        "transcript_gz_size": s.get("transcript_gz_size", 0),
        "uploaded_at": uploaded_at,
        "redactions": s.get("redactions") or 0,
    }


def _save_parquet(sessions: list[dict], path: Path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = [_flatten_session(s) for s in sessions]
    if not rows:
        return
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path, compression="zstd")


def _load_latest_timestamp(path: Path) -> str | None:
    """Read the latest uploaded_at from existing Parquet."""
    import pyarrow.parquet as pq

    table = pq.read_table(path, columns=["uploaded_at"])
    timestamps = [t for t in table.column("uploaded_at").to_pylist() if t]
    return max(timestamps) if timestamps else None


def _merge_parquet(existing_path: Path, new_sessions: list[dict]) -> tuple[int, int]:
    """Merge new sessions into existing Parquet. Returns (total, added)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    existing = pq.read_table(existing_path)
    existing_ids = set(existing.column("session_id").to_pylist())

    truly_new = [s for s in new_sessions if s.get("session_id") not in existing_ids]
    if not truly_new:
        return existing.num_rows, 0

    new_table = pa.Table.from_pylist([_flatten_session(s) for s in truly_new])
    merged = pa.concat_tables([existing, new_table], promote_options="default")
    pq.write_table(merged, existing_path, compression="zstd")
    return merged.num_rows, len(truly_new)


def _download_transcripts(
    session_ids: list[str], output_dir: Path, url: str, token: str, workers: int
):
    output_dir.mkdir(parents=True, exist_ok=True)
    existing = {f.stem for f in output_dir.glob("*.jsonl.gz")}
    to_download = [sid for sid in session_ids if sid not in existing]

    if not to_download:
        print(f"Transcripts up to date ({len(existing)} cached)")
        return

    print(f"Downloading {len(to_download)} transcripts ({len(existing)} cached)...")
    success = failed = 0

    def _one(sid):
        data = _api_get(url, token, f"/api/session/{sid}/raw")
        (output_dir / f"{sid}.jsonl.gz").write_bytes(data)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_one, sid): sid for sid in to_download}
        for i, future in enumerate(as_completed(futures), 1):
            sid = futures[future]
            try:
                future.result()
                success += 1
            except Exception as e:
                failed += 1
                print(f"  {sid[:12]}... FAILED: {e}", file=sys.stderr)
            if i % 50 == 0 or i == len(to_download):
                print(f"  [{i}/{len(to_download)}] {success} ok, {failed} failed")

    print(f"Transcripts: {success} downloaded, {failed} failed")


def run(output: str | None = None, transcripts: bool = False, workers: int = 4):
    url, token = get_credentials()
    if not url or not token:
        print("Not configured. Run 'gleaner setup URL TOKEN' first.", file=sys.stderr)
        sys.exit(1)

    try:
        import pyarrow  # noqa: F401
    except ImportError:
        print("pyarrow required: pip install 'gleaner-cli[pull]'", file=sys.stderr)
        sys.exit(1)

    data_dir = Path(output) if output else DEFAULT_DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = data_dir / "sessions.parquet"

    # Incremental sync: only fetch sessions newer than our latest
    since = None
    if parquet_path.exists():
        try:
            since = _load_latest_timestamp(parquet_path)
            if since:
                print(f"Incremental sync (since {since[:19]})")
        except Exception:
            pass

    sessions = _fetch_sessions(url, token, since=since)

    if parquet_path.exists() and since is not None:
        total, added = _merge_parquet(parquet_path, sessions)
        if added:
            print(f"Added {added} sessions (total: {total})")
        else:
            print(f"Up to date ({total} sessions)")
    elif sessions:
        _save_parquet(sessions, parquet_path)
        print(f"Saved {len(sessions)} sessions -> {parquet_path}")
    else:
        print("No sessions found on server")
        return

    if transcripts:
        # Get all session IDs for transcript download
        if parquet_path.exists():
            import pyarrow.parquet as pq
            table = pq.read_table(parquet_path, columns=["session_id"])
            all_ids = table.column("session_id").to_pylist()
        else:
            all_ids = [s["session_id"] for s in sessions if s.get("session_id")]
        _download_transcripts(all_ids, data_dir / "transcripts", url, token, workers)

    print(f"\nData: {parquet_path}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Download Gleaner sessions for local analysis"
    )
    parser.add_argument(
        "-o", "--output", help=f"Output directory (default: {DEFAULT_DATA_DIR})"
    )
    parser.add_argument(
        "--transcripts", action="store_true", help="Also download raw transcripts"
    )
    parser.add_argument(
        "-j", "--workers", type=int, default=4, help="Parallel downloads (default: 4)"
    )
    args = parser.parse_args()
    run(output=args.output, transcripts=args.transcripts, workers=args.workers)


if __name__ == "__main__":
    main()
