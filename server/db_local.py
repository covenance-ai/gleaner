"""Local vault storage backend: reads sessions from ~/.gleaner/.

Implements the same interface as db.py / db_mock.py but reads from
the local parquet index and JSONL transcript files. No cloud dependencies.
"""

import getpass
import gzip
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pyarrow.parquet as pq

VAULT_DIR = Path.home() / ".gleaner"
LOCAL_USER = getpass.getuser()

_index_cache: list[dict] | None = None
_index_mtime: float = 0


def _load_index() -> list[dict]:
    """Load parquet index, re-reading only when the file changes."""
    global _index_cache, _index_mtime
    path = VAULT_DIR / "index.parquet"
    if not path.exists():
        _index_cache = []
        return []
    mtime = path.stat().st_mtime
    if _index_cache is not None and mtime == _index_mtime:
        return _index_cache
    _index_cache = pq.read_table(path).to_pylist()
    _index_mtime = mtime
    return _index_cache


def _duration_seconds(first_ts: str, last_ts: str) -> float:
    if not first_ts or not last_ts:
        return 0.0
    try:
        s = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
        e = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
        return max((e - s).total_seconds(), 0)
    except (ValueError, AttributeError):
        return 0.0


def _aggregate_tool_usage(rows: list[dict]) -> dict[str, int]:
    """Sum tool counts across rows from tool_counts_json."""
    totals: dict[str, int] = defaultdict(int)
    for r in rows:
        try:
            for tool, count in json.loads(r.get("tool_counts_json", "{}")).items():
                totals[tool] += count
        except (json.JSONDecodeError, TypeError):
            pass
    return dict(sorted(totals.items(), key=lambda x: -x[1]))


def _count_by_date(rows: list[dict]) -> dict[str, int]:
    """Count sessions per date from first_timestamp."""
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        ts = (r.get("first_timestamp") or "")[:10]
        if ts:
            counts[ts] += 1
    return counts


def _row_to_session(row: dict, include_tool_counts: bool = False) -> dict:
    """Convert a parquet row to the API session shape."""
    result = {
        "session_id": row["session_id"],
        "topic": row.get("topic", ""),
        "project": row.get("project", ""),
        "cwd": row.get("cwd", ""),
        "message_count": row.get("message_count", 0),
        "user_message_count": row.get("user_message_count", 0),
        "assistant_message_count": row.get("assistant_message_count", 0),
        "tool_use_count": row.get("tool_use_count", 0),
        "first_timestamp": row.get("first_timestamp"),
        "last_timestamp": row.get("last_timestamp"),
        "provenance": {
            "user": row.get("user", ""),
            "host": row.get("host", ""),
            "platform": row.get("platform", ""),
        },
        "transcript_size": row.get("transcript_size", 0),
        "uploaded_at": row.get("ingested_at", ""),
    }
    if include_tool_counts:
        try:
            result["tool_counts"] = json.loads(row.get("tool_counts_json", "{}"))
        except (json.JSONDecodeError, TypeError):
            result["tool_counts"] = {}
    return result


# --- Tokens (stubs) ---


def validate_token(token: str) -> dict | None:
    return {"name": LOCAL_USER, "active": True}


def create_token(name: str, issued_to: str = "", notes: str = "") -> str:
    raise NotImplementedError("Tokens not available in local mode")


def list_tokens() -> list[dict]:
    return []


def revoke_token(id_or_prefix: str) -> bool:
    return False


# --- Users (stubs) ---


def get_user_by_email(email: str) -> dict | None:
    return None


def create_or_update_user(
    email: str, username: str, display_name: str = "", picture: str = ""
) -> dict:
    raise NotImplementedError("User management not available in local mode")


def is_username_taken(username: str, exclude_email: str = "") -> bool:
    return False


def list_user_tokens(owner_email: str) -> list[dict]:
    return []


def create_user_token(username: str, owner_email: str, token_name: str = "") -> str:
    raise NotImplementedError("Tokens not available in local mode")


def revoke_user_token(id_or_prefix: str, owner_email: str) -> bool:
    return False


# --- Backup (stub) ---


def export_firestore() -> dict:
    return {"status": "not_available"}


# --- Sessions ---


def store_session(
    session_id: str,
    metadata: dict,
    provenance: dict,
    transcript_gz: bytes,
    transcript_size: int,
):
    raise NotImplementedError("Upload not supported in local mode. Use 'gleaner collect'.")


def get_session(session_id: str) -> dict | None:
    for row in _load_index():
        if row["session_id"] == session_id:
            return _row_to_session(row, include_tool_counts=True)
    return None


def get_session_transcript(session_id: str) -> bytes | None:
    raw_path = VAULT_DIR / "sessions" / session_id / "raw.jsonl"
    if not raw_path.exists():
        return None
    return gzip.compress(raw_path.read_bytes())


def list_sessions(
    user: str | None = None,
    project: str | None = None,
    limit: int = 100,
    ids_only: bool = False,
    uploaded_after: datetime | None = None,
    keep_tool_counts: bool = False,
    session_date: str | None = None,
) -> list:
    rows = _load_index()

    if user:
        rows = [r for r in rows if r.get("user") == user]
    if project:
        rows = [r for r in rows if r.get("project") == project]
    if uploaded_after:
        after_str = uploaded_after.isoformat()
        rows = [r for r in rows if (r.get("ingested_at") or "") > after_str]
    if session_date:
        rows = [r for r in rows if (r.get("first_timestamp") or "")[:10] == session_date]

    rows.sort(key=lambda r: r.get("first_timestamp") or "", reverse=True)

    if limit:
        rows = rows[:limit]

    if ids_only:
        return [r["session_id"] for r in rows]

    return [_row_to_session(r, include_tool_counts=keep_tool_counts) for r in rows]


def get_user_stats(username: str) -> dict:
    rows = [r for r in _load_index() if r.get("user") == username]
    return _compute_user_stats(username, rows)


def _compute_user_stats(username: str, rows: list[dict]) -> dict:
    empty = {
        "user": username,
        "total_sessions": 0,
        "avg_messages_per_session": 0,
        "last_session": None,
        "week_stats": {
            "sessions": 0, "sessions_prev_week": 0, "messages": 0,
            "avg_duration_seconds": 0, "total_duration_seconds": 0,
            "active_days": 0, "most_active_project": "",
        },
        "heatmap": [], "tool_usage": {}, "project_usage": {}, "recent_sessions": [],
    }
    if not rows:
        return empty

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    prev_week_start = week_start - timedelta(days=7)
    heatmap_start = (today.replace(day=1) - timedelta(days=90)).replace(day=1)

    total_sessions = len(rows)
    total_messages = sum(r.get("message_count", 0) for r in rows)

    # Sort by first_timestamp descending for recent sessions
    sorted_rows = sorted(rows, key=lambda r: r.get("first_timestamp") or "", reverse=True)

    # Last session
    last_row = sorted_rows[0]
    last_session = _row_to_session(last_row, include_tool_counts=True)

    # Recent sessions
    recent = [_row_to_session(r) for r in sorted_rows[:10]]

    # Week stats
    week_sessions = 0
    week_messages = 0
    week_duration = 0.0
    week_dates: set[str] = set()
    prev_week_sessions = 0
    week_projects: dict[str, int] = defaultdict(int)

    for r in rows:
        ts = (r.get("first_timestamp") or "")[:10]
        if not ts:
            continue
        dur = _duration_seconds(r.get("first_timestamp", ""), r.get("last_timestamp", ""))
        if ts >= week_start.isoformat():
            week_sessions += 1
            week_messages += r.get("message_count", 0)
            week_duration += dur
            week_dates.add(ts)
            proj = r.get("project", "")
            if proj:
                week_projects[proj] += 1
        elif ts >= prev_week_start.isoformat():
            prev_week_sessions += 1

    most_active = max(week_projects, key=week_projects.get) if week_projects else ""

    date_counts = _count_by_date(rows)
    heatmap = []
    d = heatmap_start
    while d <= today:
        ds = d.isoformat()
        heatmap.append({"date": ds, "count": date_counts.get(ds, 0)})
        d += timedelta(days=1)

    project_usage: dict[str, int] = defaultdict(int)
    for r in rows:
        proj = r.get("project", "")
        if proj:
            project_usage[proj] += 1

    return {
        "user": username,
        "total_sessions": total_sessions,
        "avg_messages_per_session": round(total_messages / total_sessions) if total_sessions else 0,
        "last_session": last_session,
        "week_stats": {
            "sessions": week_sessions,
            "sessions_prev_week": prev_week_sessions,
            "messages": week_messages,
            "avg_duration_seconds": round(week_duration / week_sessions) if week_sessions else 0,
            "total_duration_seconds": round(week_duration),
            "active_days": len(week_dates),
            "most_active_project": most_active,
        },
        "heatmap": heatmap,
        "tool_usage": _aggregate_tool_usage(rows),
        "project_usage": dict(sorted(project_usage.items(), key=lambda x: -x[1])),
        "recent_sessions": recent,
    }


def get_stats() -> dict:
    rows = _load_index()
    if not rows:
        return {
            "total_sessions": 0, "total_messages": 0, "total_tool_uses": 0,
            "unique_users": 0, "unique_projects": 0, "avg_duration_seconds": 0,
            "active_this_week": 0, "users": [], "projects": [],
            "tool_usage": {}, "timeline": [], "user_stats": {},
            "project_stats": {}, "recent_sessions": [],
        }

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_start_str = week_start.isoformat()

    total_sessions = len(rows)
    total_messages = sum(r.get("message_count", 0) for r in rows)
    total_tool_uses = sum(r.get("tool_use_count", 0) for r in rows)
    total_duration = sum(
        _duration_seconds(r.get("first_timestamp", ""), r.get("last_timestamp", ""))
        for r in rows
    )

    users = sorted({r.get("user", "") for r in rows if r.get("user")})
    projects = sorted({r.get("project", "") for r in rows if r.get("project")})

    # Per-user stats
    by_user: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        u = r.get("user", "")
        if u:
            by_user[u].append(r)

    user_stats = {}
    active_this_week = 0
    for username, user_rows in by_user.items():
        sessions = len(user_rows)
        messages = sum(r.get("message_count", 0) for r in user_rows)
        tool_uses = sum(r.get("tool_use_count", 0) for r in user_rows)
        dur = sum(
            _duration_seconds(r.get("first_timestamp", ""), r.get("last_timestamp", ""))
            for r in user_rows
        )
        last_active = max((r.get("first_timestamp") or "" for r in user_rows), default="")

        # Top project
        proj_counts: dict[str, int] = defaultdict(int)
        week_dates: set[str] = set()
        for r in user_rows:
            p = r.get("project", "")
            if p:
                proj_counts[p] += 1
            ts = (r.get("first_timestamp") or "")[:10]
            if ts >= week_start_str:
                week_dates.add(ts)

        top_project = max(proj_counts, key=proj_counts.get) if proj_counts else ""
        week_days = len(week_dates)
        if week_days > 0:
            active_this_week += 1

        user_stats[username] = {
            "sessions": sessions,
            "messages": messages,
            "tool_uses": tool_uses,
            "last_active": last_active,
            "avg_duration_seconds": round(dur / sessions) if sessions else 0,
            "top_project": top_project,
            "active_days_this_week": week_days,
        }

    user_stats = dict(sorted(user_stats.items(), key=lambda x: -x[1]["sessions"]))

    # Per-project stats
    by_project: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        p = r.get("project", "")
        if p:
            by_project[p].append(r)

    project_stats = {}
    for name, proj_rows in sorted(by_project.items(), key=lambda x: -len(x[1]))[:15]:
        project_stats[name] = {
            "sessions": len(proj_rows),
            "messages": sum(r.get("message_count", 0) for r in proj_rows),
            "users": sorted({r.get("user", "") for r in proj_rows if r.get("user")}),
        }

    date_counts = _count_by_date(rows)
    timeline = []
    for i in range(29, -1, -1):
        day = (today - timedelta(days=i)).isoformat()
        timeline.append({"date": day, "count": date_counts.get(day, 0)})

    sorted_rows = sorted(rows, key=lambda r: r.get("first_timestamp") or "", reverse=True)
    recent = [_row_to_session(r) for r in sorted_rows[:10]]

    return {
        "total_sessions": total_sessions,
        "total_messages": total_messages,
        "total_tool_uses": total_tool_uses,
        "unique_users": len(users),
        "unique_projects": len(projects),
        "avg_duration_seconds": round(total_duration / total_sessions) if total_sessions else 0,
        "active_this_week": active_this_week,
        "users": users,
        "projects": projects,
        "tool_usage": _aggregate_tool_usage(rows),
        "timeline": timeline,
        "user_stats": user_stats,
        "project_stats": project_stats,
        "recent_sessions": recent,
    }
