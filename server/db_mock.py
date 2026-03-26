"""In-memory mock of db.py for local development. No GCP dependencies needed.

Provides the same interface as db.py with realistic sample data pre-loaded.
Activate by setting GLEANER_MOCK=1 before starting the server.
"""

import gzip
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

# --- In-memory stores ---
_tokens: dict[str, dict] = {}  # hash -> token data
_sessions: dict[str, dict] = {}  # session_id -> metadata
_transcripts: dict[str, bytes] = {}  # session_id -> gzipped bytes
_counters: dict[str, dict] = {}  # "global" / "user:{name}" -> counter doc
_users: dict[str, dict] = {}  # email -> user data

# --- Seed data ---

_USERS = ["ikamen", "alice", "bob"]
_HOSTS = ["MacBook-Pro", "dev-server-1", "alice-mbp", "bob-desktop"]
_PROJECTS = [
    "-Users-ikamen-ai-workspace-ilya-gleaner",
    "-Users-ikamen-ai-workspace-ilya-kodo",
    "-Users-ikamen-covenance-overseer",
    "-Users-alice-projects-frontend",
    "-Users-bob-projects-api",
]
_TOOLS = ["Read", "Edit", "Bash", "Grep", "Glob", "Write", "Agent", "Skill"]
_TOPICS = [
    "add personal home page to dashboard",
    "fix authentication bug in login flow",
    "refactor database queries for performance",
    "update CI pipeline configuration",
    "implement webhook retry logic",
    "add unit tests for scrubbing module",
    "deploy new version to production",
    "review PR #42 changes",
    "debug flaky test in e2e suite",
    "add CORS headers to API endpoints",
    "implement rate limiting middleware",
    "update README with deployment instructions",
    "fix CSS layout issue on mobile",
    "add dark mode support to dashboard",
    "optimize Docker image size",
    "set up monitoring alerts",
    "migrate database schema",
    "implement session search feature",
    "add export to CSV functionality",
    "fix timezone handling in timestamps",
]


def _seed():
    """Generate realistic mock sessions spanning the last 90 days."""
    import random

    random.seed(42)  # Reproducible
    now = datetime.now(timezone.utc)

    # Create mock users
    _users["ikamen@example.com"] = {
        "username": "ikamen",
        "email": "ikamen@example.com",
        "display_name": "Ilya Kamen",
        "picture": "",
        "onboarded": True,
        "created_at": now - timedelta(days=60),
    }
    _users["alice@example.com"] = {
        "username": "alice",
        "email": "alice@example.com",
        "display_name": "Alice",
        "picture": "",
        "onboarded": True,
        "created_at": now - timedelta(days=45),
    }

    # Create a token for local dev
    raw_token = "gl_mock_local_dev_token_1234567890abcdef"
    _tokens[_token_hash(raw_token)] = {
        "name": "ikamen",
        "issued_to": "ikamen@example.com",
        "owner_email": "ikamen@example.com",
        "notes": "Local dev token",
        "prefix": raw_token[:8],
        "active": True,
        "created_at": now - timedelta(days=30),
        "last_used_at": now,
        "usage_count": 100,
    }

    # Generate sessions
    for i in range(80):
        days_ago = random.randint(0, 89)
        hour = random.choice([9, 10, 11, 14, 15, 16, 17, 20, 21, 22])
        minute = random.randint(0, 59)
        start = now - timedelta(days=days_ago, hours=random.randint(0, 3))
        start = start.replace(hour=hour, minute=minute, second=0, microsecond=0)
        duration_min = random.randint(2, 120)
        end = start + timedelta(minutes=duration_min)

        user = random.choices(_USERS, weights=[0.5, 0.3, 0.2])[0]
        host = random.choice(_HOSTS)
        project = random.choice(_PROJECTS)
        topic = random.choice(_TOPICS)

        tool_counts = {}
        for tool in random.sample(_TOOLS, k=random.randint(2, 6)):
            tool_counts[tool] = random.randint(1, 50)

        msg_count = random.randint(4, 60)
        user_msgs = msg_count // 2
        assistant_msgs = msg_count - user_msgs
        tool_use_count = sum(tool_counts.values())
        transcript_size = random.randint(5000, 200000)

        sid = f"mock-session-{i:04d}"
        _sessions[sid] = {
            "session_id": sid,
            "topic": topic,
            "project": project,
            "cwd": f"/Users/{user}/projects/{project.split('-')[-1]}",
            "message_count": msg_count,
            "user_message_count": user_msgs,
            "assistant_message_count": assistant_msgs,
            "tool_use_count": tool_use_count,
            "tool_counts": tool_counts,
            "first_timestamp": start.isoformat(),
            "last_timestamp": end.isoformat(),
            "provenance": {
                "user": user,
                "host": host,
                "platform": "Darwin arm64",
            },
            "transcript_size": transcript_size,
            "transcript_gz_size": transcript_size // 4,
            "gcs_path": f"sessions/{sid}.jsonl.gz",
            "uploaded_at": end + timedelta(seconds=2),
        }

        # Minimal mock transcript
        transcript_lines = [
            json.dumps({"type": "user", "timestamp": start.isoformat(),
                         "message": {"content": topic}}),
            json.dumps({"type": "assistant", "timestamp": end.isoformat(),
                         "message": {"content": "Done."}}),
        ]
        _transcripts[sid] = gzip.compress("\n".join(transcript_lines).encode())

    _build_counters()


def _build_counters():
    """Build counter docs from all sessions (mirrors backfill)."""
    g = {
        "total_sessions": 0, "total_messages": 0, "total_tool_uses": 0,
        "tool_usage": {}, "daily": {}, "users": {}, "projects": {},
    }
    ucs: dict[str, dict] = {}

    for sid, data in _sessions.items():
        username = data.get("provenance", {}).get("user", "")
        project = data.get("project", "")
        msg_count = data.get("message_count", 0)
        tool_count = data.get("tool_use_count", 0)
        first_ts = data.get("first_timestamp", "")
        last_ts = data.get("last_timestamp", "")
        date_str = first_ts[:10] if len(first_ts) >= 10 else ""

        duration = 0.0
        if first_ts and last_ts:
            try:
                s = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
                e = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                duration = (e - s).total_seconds()
            except (ValueError, AttributeError):
                pass

        g["total_sessions"] += 1
        g["total_messages"] += msg_count
        g["total_tool_uses"] += tool_count

        for tool, count in data.get("tool_counts", {}).items():
            g["tool_usage"][tool] = g["tool_usage"].get(tool, 0) + count

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

        if username:
            if username not in ucs:
                ucs[username] = {
                    "total_sessions": 0, "total_messages": 0, "total_tool_uses": 0,
                    "total_duration_seconds": 0.0, "tool_usage": {}, "project_usage": {},
                    "daily": {}, "last_session_id": "", "last_active": "",
                }
            u = ucs[username]
            u["total_sessions"] += 1
            u["total_messages"] += msg_count
            u["total_tool_uses"] += tool_count
            u["total_duration_seconds"] += duration
            if first_ts and first_ts > u["last_active"]:
                u["last_session_id"] = sid
                u["last_active"] = first_ts
            for tool, count in data.get("tool_counts", {}).items():
                u["tool_usage"][tool] = u["tool_usage"].get(tool, 0) + count
            if project:
                u["project_usage"][project] = u["project_usage"].get(project, 0) + 1
            if date_str:
                if date_str not in u["daily"]:
                    u["daily"][date_str] = {"s": 0, "m": 0, "d": 0.0}
                u["daily"][date_str]["s"] += 1
                u["daily"][date_str]["m"] += msg_count
                u["daily"][date_str]["d"] += duration

    # Split global counter into 4 docs (mirrors Firestore split)
    _counters["global"] = {
        "total_sessions": g["total_sessions"],
        "total_messages": g["total_messages"],
        "total_tool_uses": g["total_tool_uses"],
        "tool_usage": g["tool_usage"],
    }
    _counters["global:daily"] = g["daily"]
    _counters["global:users"] = g["users"]
    _counters["global:projects"] = g["projects"]
    for username, counter in ucs.items():
        _counters[f"user:{username}"] = counter


# --- Token functions ---


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_token(name: str, issued_to: str = "", notes: str = "") -> str:
    token = f"gl_{secrets.token_urlsafe(32)}"
    _tokens[_token_hash(token)] = {
        "name": name,
        "issued_to": issued_to,
        "notes": notes,
        "prefix": token[:8],
        "active": True,
        "created_at": datetime.now(timezone.utc),
        "last_used_at": None,
        "usage_count": 0,
    }
    return token


def validate_token(token: str) -> dict | None:
    h = _token_hash(token)
    data = _tokens.get(h)
    if not data or not data.get("active"):
        return None
    data["last_used_at"] = datetime.now(timezone.utc)
    data["usage_count"] = data.get("usage_count", 0) + 1
    return data


def list_tokens() -> list[dict]:
    return [{"id": k, **v} for k, v in _tokens.items()]


def revoke_token(id_or_prefix: str) -> bool:
    if id_or_prefix in _tokens:
        _tokens[id_or_prefix]["active"] = False
        return True
    for h, data in _tokens.items():
        if data.get("prefix", "").startswith(id_or_prefix):
            data["active"] = False
            return True
    return False


# --- Users ---


def get_user_by_email(email: str) -> dict | None:
    return _users.get(email)


def create_or_update_user(
    email: str, username: str, display_name: str = "", picture: str = ""
) -> dict:
    existing = _users.get(email, {})
    user_data = {
        "username": username,
        "email": email,
        "display_name": display_name,
        "picture": picture,
        "onboarded": True,
        "created_at": existing.get("created_at", datetime.now(timezone.utc)),
    }
    _users[email] = user_data
    return user_data


def is_username_taken(username: str, exclude_email: str = "") -> bool:
    return any(
        u["username"] == username for e, u in _users.items() if e != exclude_email
    )


def list_user_tokens(owner_email: str) -> list[dict]:
    return [
        {"id": k, **v}
        for k, v in _tokens.items()
        if v.get("owner_email") == owner_email
    ]


def create_user_token(username: str, owner_email: str, token_name: str = "") -> str:
    token = f"gl_{secrets.token_urlsafe(32)}"
    _tokens[_token_hash(token)] = {
        "name": username,
        "issued_to": owner_email,
        "owner_email": owner_email,
        "notes": token_name or "Dashboard",
        "prefix": token[:8],
        "active": True,
        "created_at": datetime.now(timezone.utc),
        "last_used_at": None,
        "usage_count": 0,
    }
    return token


def revoke_user_token(id_or_prefix: str, owner_email: str) -> bool:
    for h, data in _tokens.items():
        if data.get("owner_email") != owner_email:
            continue
        if h == id_or_prefix or data.get("prefix", "").startswith(id_or_prefix):
            data["active"] = False
            return True
    return False


# --- Backup ---


def export_firestore() -> dict:
    return {"status": "mock_export", "output_uri": "gs://mock/backups/mock", "operation": "mock-op"}


# --- Session functions ---


def _update_mock_counters(session_id: str, metadata: dict, provenance: dict):
    """Incrementally update in-memory counter docs (mirrors db._update_counters)."""
    username = provenance.get("user", "")
    project = metadata.get("project", "")
    msg_count = metadata.get("message_count", 0)
    tool_count = metadata.get("tool_use_count", 0)
    first_ts = metadata.get("first_timestamp", "")
    last_ts = metadata.get("last_timestamp", "")
    date_str = first_ts[:10] if len(first_ts) >= 10 else ""

    duration = 0.0
    if first_ts and last_ts:
        try:
            s = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
            e = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            duration = (e - s).total_seconds()
        except (ValueError, AttributeError):
            pass

    # Split global counter (mirrors Firestore split)
    if "global" not in _counters:
        _counters["global"] = {"total_sessions": 0, "total_messages": 0, "total_tool_uses": 0, "tool_usage": {}}
        _counters["global:daily"] = {}
        _counters["global:users"] = {}
        _counters["global:projects"] = {}
    g = _counters["global"]
    g["total_sessions"] += 1
    g["total_messages"] += msg_count
    g["total_tool_uses"] += tool_count
    for tool, count in metadata.get("tool_counts", {}).items():
        g["tool_usage"][tool] = g["tool_usage"].get(tool, 0) + count
    if date_str:
        daily = _counters["global:daily"]
        daily[date_str] = daily.get(date_str, 0) + 1
    if username:
        users = _counters["global:users"]
        if username not in users:
            users[username] = {
                "sessions": 0, "messages": 0, "tool_uses": 0,
                "total_duration_seconds": 0.0, "last_active": "",
            }
        gu = users[username]
        gu["sessions"] += 1
        gu["messages"] += msg_count
        gu["tool_uses"] += tool_count
        gu["total_duration_seconds"] += duration
        if first_ts:
            gu["last_active"] = first_ts
    if project:
        projects = _counters["global:projects"]
        if project not in projects:
            projects[project] = {"sessions": 0, "messages": 0, "users": []}
        gp = projects[project]
        gp["sessions"] += 1
        gp["messages"] += msg_count
        if username and username not in gp["users"]:
            gp["users"].append(username)

    if username:
        key = f"user:{username}"
        if key not in _counters:
            _counters[key] = {
                "total_sessions": 0, "total_messages": 0, "total_tool_uses": 0,
                "total_duration_seconds": 0.0, "tool_usage": {}, "project_usage": {},
                "daily": {}, "last_session_id": "", "last_active": "",
            }
        u = _counters[key]
        u["total_sessions"] += 1
        u["total_messages"] += msg_count
        u["total_tool_uses"] += tool_count
        u["total_duration_seconds"] += duration
        u["last_session_id"] = session_id
        if first_ts:
            u["last_active"] = first_ts
        for tool, count in metadata.get("tool_counts", {}).items():
            u["tool_usage"][tool] = u["tool_usage"].get(tool, 0) + count
        if project:
            u["project_usage"][project] = u["project_usage"].get(project, 0) + 1
        if date_str:
            if date_str not in u["daily"]:
                u["daily"][date_str] = {"s": 0, "m": 0, "d": 0.0}
            u["daily"][date_str]["s"] += 1
            u["daily"][date_str]["m"] += msg_count
            u["daily"][date_str]["d"] += duration


def _recent_sessions(user: str | None = None, limit: int = 10) -> list[dict]:
    results = sorted(
        _sessions.values(),
        key=lambda s: s.get("uploaded_at", ""),
        reverse=True,
    )
    if user:
        results = [s for s in results if s.get("provenance", {}).get("user") == user]
    results = results[:limit]
    return [
        {
            "session_id": s.get("session_id", ""),
            "topic": s.get("topic", ""),
            "project": s.get("project", ""),
            "cwd": s.get("cwd", ""),
            "user": s.get("provenance", {}).get("user", ""),
            "message_count": s.get("message_count", 0),
            "tool_use_count": s.get("tool_use_count", 0),
            "first_timestamp": s.get("first_timestamp"),
            "last_timestamp": s.get("last_timestamp"),
            "provenance": s.get("provenance", {}),
            "transcript_size": s.get("transcript_size", 0),
        }
        for s in results
    ]


def store_session(
    session_id: str,
    metadata: dict,
    provenance: dict,
    transcript_gz: bytes,
    transcript_size: int,
):
    doc = {
        **metadata,
        "session_id": session_id,
        "provenance": provenance,
        "transcript_size": transcript_size,
        "transcript_gz_size": len(transcript_gz),
        "gcs_path": f"sessions/{session_id}.jsonl.gz",
        "uploaded_at": datetime.now(timezone.utc),
    }
    _sessions[session_id] = doc
    _transcripts[session_id] = transcript_gz
    _update_mock_counters(session_id, metadata, provenance)


def get_session(session_id: str) -> dict | None:
    data = _sessions.get(session_id)
    if data is None:
        return None
    return {**data, "session_id": session_id}


def get_session_transcript(session_id: str) -> bytes | None:
    return _transcripts.get(session_id)


def list_sessions(
    user: str | None = None,
    project: str | None = None,
    limit: int = 100,
    ids_only: bool = False,
) -> list:
    results = sorted(
        _sessions.values(),
        key=lambda s: s.get("uploaded_at", ""),
        reverse=True,
    )
    if user:
        results = [s for s in results if s.get("provenance", {}).get("user") == user]
    if project:
        results = [s for s in results if s.get("project") == project]
    results = results[:limit]
    if ids_only:
        return [s.get("session_id", "") for s in results]
    return [{**s, "session_id": s.get("session_id", "")} for s in results]


def get_user_stats(username: str) -> dict:
    """Personal stats from counter doc — mirrors db.get_user_stats."""
    from collections import defaultdict

    now = datetime.now(timezone.utc)
    today = now.date()
    week_start = today - timedelta(days=today.weekday())
    prev_week_start = week_start - timedelta(days=7)
    heatmap_start = (today.replace(day=1) - timedelta(days=90)).replace(day=1)
    week_start_str = week_start.isoformat()
    prev_week_start_str = prev_week_start.isoformat()

    u = _counters.get(f"user:{username}")
    if not u:
        return {
            "user": username, "total_sessions": 0, "avg_messages_per_session": 0,
            "last_session": None, "week_stats": {
                "sessions": 0, "sessions_prev_week": 0, "messages": 0,
                "avg_duration_seconds": 0, "total_duration_seconds": 0,
                "active_days": 0, "most_active_project": "",
            },
            "heatmap": [], "tool_usage": {}, "project_usage": {}, "recent_sessions": [],
        }

    daily = u.get("daily", {})

    week_sessions = 0
    week_messages = 0
    week_duration = 0.0
    week_active_days = 0
    prev_week_sessions = 0
    for date_str, day_data in daily.items():
        if not isinstance(day_data, dict):
            continue
        if date_str >= week_start_str:
            s = day_data.get("s", 0)
            week_sessions += s
            week_messages += day_data.get("m", 0)
            week_duration += day_data.get("d", 0)
            if s > 0:
                week_active_days += 1
        elif date_str >= prev_week_start_str:
            prev_week_sessions += day_data.get("s", 0)

    heatmap_list = []
    d = heatmap_start
    while d <= today:
        ds = d.isoformat()
        day_data = daily.get(ds, {})
        count = day_data.get("s", 0) if isinstance(day_data, dict) else 0
        heatmap_list.append({"date": ds, "count": count})
        d += timedelta(days=1)

    recent = _recent_sessions(user=username, limit=20)

    week_projects: dict[str, int] = defaultdict(int)
    for s in recent:
        ts = s.get("first_timestamp", "") or ""
        if ts[:10] >= week_start_str:
            proj = s.get("project", "")
            if proj:
                week_projects[proj] += 1
    most_active = max(week_projects, key=week_projects.get) if week_projects else ""

    last_sid = u.get("last_session_id", "")
    last_session = get_session(last_sid) if last_sid else None

    total_sessions = u.get("total_sessions", 0)
    total_messages = u.get("total_messages", 0)

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
            "active_days": week_active_days,
            "most_active_project": most_active,
        },
        "heatmap": heatmap_list,
        "tool_usage": dict(sorted(u.get("tool_usage", {}).items(), key=lambda x: -x[1])),
        "project_usage": dict(sorted(u.get("project_usage", {}).items(), key=lambda x: -x[1])),
        "recent_sessions": recent[:10],
    }


def get_stats() -> dict:
    """Aggregate stats from counter doc — mirrors db.get_stats."""
    g = _counters.get("global")
    if not g:
        return {
            "total_sessions": 0, "total_messages": 0, "total_tool_uses": 0,
            "unique_users": 0, "unique_projects": 0, "avg_duration_seconds": 0,
            "active_this_week": 0, "users": [], "projects": [],
            "tool_usage": {}, "timeline": [], "user_stats": {},
            "project_stats": {}, "recent_sessions": [],
        }

    users_map = _counters.get("global:users", {})
    projects_map = _counters.get("global:projects", {})
    daily_map = _counters.get("global:daily", {})

    today = datetime.now(timezone.utc).date()
    week_start_str = (today - timedelta(days=today.weekday())).isoformat()

    user_stats = {}
    active_this_week = 0
    for username, info in users_map.items():
        sessions = info.get("sessions", 0)
        dur = info.get("total_duration_seconds", 0)

        uc = _counters.get(f"user:{username}", {})
        project_usage = uc.get("project_usage", {})
        udaily = uc.get("daily", {})

        top_project = max(project_usage, key=project_usage.get) if project_usage else ""
        week_days = sum(
            1 for d, v in udaily.items()
            if d >= week_start_str and isinstance(v, dict) and v.get("s", 0) > 0
        )
        if week_days > 0:
            active_this_week += 1

        user_stats[username] = {
            "sessions": sessions,
            "messages": info.get("messages", 0),
            "tool_uses": info.get("tool_uses", 0),
            "last_active": info.get("last_active", ""),
            "avg_duration_seconds": round(dur / sessions) if sessions else 0,
            "top_project": top_project,
            "active_days_this_week": week_days,
        }

    sorted_user_stats = dict(sorted(user_stats.items(), key=lambda x: -x[1]["sessions"]))

    project_stats = {}
    for name, info in projects_map.items():
        project_stats[name] = {
            "sessions": info.get("sessions", 0),
            "messages": info.get("messages", 0),
            "users": sorted(info.get("users", [])),
        }
    sorted_project_stats = dict(sorted(project_stats.items(), key=lambda x: -x[1]["sessions"])[:15])

    timeline = []
    for i in range(29, -1, -1):
        day = (today - timedelta(days=i)).isoformat()
        timeline.append({"date": day, "count": daily_map.get(day, 0)})

    recent_sessions = _recent_sessions(limit=10)

    total_dur = sum(info.get("total_duration_seconds", 0) for info in users_map.values())
    total_sess = g.get("total_sessions", 0)

    return {
        "total_sessions": total_sess,
        "total_messages": g.get("total_messages", 0),
        "total_tool_uses": g.get("total_tool_uses", 0),
        "unique_users": len(users_map),
        "unique_projects": len(projects_map),
        "avg_duration_seconds": round(total_dur / total_sess) if total_sess else 0,
        "active_this_week": active_this_week,
        "users": sorted(users_map.keys()),
        "projects": sorted(projects_map.keys()),
        "tool_usage": dict(sorted(g.get("tool_usage", {}).items(), key=lambda x: -x[1])),
        "timeline": timeline,
        "user_stats": sorted_user_stats,
        "project_stats": sorted_project_stats,
        "recent_sessions": recent_sessions,
    }


# Seed on import
_seed()
