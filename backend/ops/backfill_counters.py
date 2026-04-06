"""Rebuild counter documents from all existing sessions in Firestore.

Run once after deploying the counter-based stats, or any time counters
get out of sync. Safe to re-run — it overwrites counters from scratch.

Usage:
    python ops/backfill_counters.py [--dry-run]
"""

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from backend import db


def build_counters_from_sessions() -> tuple[dict, dict[str, dict]]:
    """Scan all sessions and produce (global_counter, {username: user_counter})."""
    g = {
        "total_sessions": 0, "total_messages": 0, "total_tool_uses": 0,
        "tool_usage": {}, "daily": {}, "users": {}, "projects": {},
    }
    user_counters: dict[str, dict] = {}

    print("Scanning sessions...", flush=True)
    count = 0
    for doc in db._db().collection("sessions").stream():
        data = doc.to_dict() or {}
        sid = doc.id
        count += 1

        username = data.get("provenance", {}).get("user", "")
        project = data.get("project", "")
        msg_count = data.get("message_count", 0)
        tool_count = data.get("tool_use_count", 0)
        first_ts = data.get("first_timestamp") or ""
        last_ts = data.get("last_timestamp") or ""
        date_str = first_ts[:10] if len(first_ts) >= 10 else ""

        duration = 0.0
        if first_ts and last_ts:
            try:
                s = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
                e = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                duration = (e - s).total_seconds()
            except (ValueError, AttributeError):
                pass

        # Global
        g["total_sessions"] += 1
        g["total_messages"] += msg_count
        g["total_tool_uses"] += tool_count

        for tool, cnt in data.get("tool_counts", {}).items():
            g["tool_usage"][tool] = g["tool_usage"].get(tool, 0) + cnt

        if date_str:
            g["daily"][date_str] = g["daily"].get(date_str, 0) + 1

        if username:
            if username not in g["users"]:
                g["users"][username] = {
                    "sessions": 0, "messages": 0, "tool_uses": 0,
                    "total_duration_seconds": 0.0, "last_active": "",
                }
            gu = g["users"][username]
            gu["sessions"] += 1
            gu["messages"] += msg_count
            gu["tool_uses"] += tool_count
            gu["total_duration_seconds"] += duration
            if first_ts and first_ts > gu["last_active"]:
                gu["last_active"] = first_ts

        if project:
            if project not in g["projects"]:
                g["projects"][project] = {"sessions": 0, "messages": 0, "users": []}
            gp = g["projects"][project]
            gp["sessions"] += 1
            gp["messages"] += msg_count
            if username and username not in gp["users"]:
                gp["users"].append(username)

        # User counter
        if username:
            if username not in user_counters:
                user_counters[username] = {
                    "total_sessions": 0, "total_messages": 0, "total_tool_uses": 0,
                    "total_duration_seconds": 0.0, "tool_usage": {}, "project_usage": {},
                    "daily": {}, "last_session_id": "", "last_active": "",
                }
            u = user_counters[username]
            u["total_sessions"] += 1
            u["total_messages"] += msg_count
            u["total_tool_uses"] += tool_count
            u["total_duration_seconds"] += duration
            if first_ts and first_ts > u["last_active"]:
                u["last_session_id"] = sid
                u["last_active"] = first_ts

            for tool, cnt in data.get("tool_counts", {}).items():
                u["tool_usage"][tool] = u["tool_usage"].get(tool, 0) + cnt
            if project:
                u["project_usage"][project] = u["project_usage"].get(project, 0) + 1
            if date_str:
                if date_str not in u["daily"]:
                    u["daily"][date_str] = {"s": 0, "m": 0, "d": 0.0}
                u["daily"][date_str]["s"] += 1
                u["daily"][date_str]["m"] += msg_count
                u["daily"][date_str]["d"] += duration

        if count % 50 == 0:
            print(f"  {count} sessions processed...", flush=True)

    print(f"Scanned {count} sessions, {len(user_counters)} users, {len(g['projects'])} projects")
    return g, user_counters


def write_counters(global_counter: dict, user_counters: dict[str, dict], dry_run: bool = False):
    """Write counter docs to Firestore (split global into 4 docs)."""
    if dry_run:
        print(f"\n[DRY RUN] Would write counters with {global_counter['total_sessions']} sessions")
        print(f"  {len(global_counter['daily'])} daily entries, {len(global_counter['users'])} users, {len(global_counter['projects'])} projects")
        for username, uc in user_counters.items():
            print(f"  counters/user:{username} — {uc['total_sessions']} sessions, {uc['total_messages']} messages")
        return

    counters = db._db().collection("counters")

    # Split global counter into 4 docs to stay under Firestore index limits
    print("Writing counters/global (totals + tools)...", flush=True)
    counters.document("global").set({
        "total_sessions": global_counter["total_sessions"],
        "total_messages": global_counter["total_messages"],
        "total_tool_uses": global_counter["total_tool_uses"],
        "tool_usage": global_counter["tool_usage"],
    })

    print(f"Writing counters/global:daily ({len(global_counter['daily'])} days)...", flush=True)
    counters.document("global:daily").set(global_counter["daily"])

    print(f"Writing counters/global:users ({len(global_counter['users'])} users)...", flush=True)
    counters.document("global:users").set(global_counter["users"])

    print(f"Writing counters/global:projects ({len(global_counter['projects'])} projects)...", flush=True)
    counters.document("global:projects").set(global_counter["projects"])

    for username, uc in user_counters.items():
        print(f"  Writing counters/user:{username}...", flush=True)
        counters.document(f"user:{username}").set(uc)

    print("Done.")


def main():
    parser = argparse.ArgumentParser(description="Rebuild counter docs from existing sessions")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be written without writing")
    args = parser.parse_args()

    global_counter, user_counters = build_counters_from_sessions()
    write_counters(global_counter, user_counters, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
