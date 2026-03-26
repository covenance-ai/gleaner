"""Gleaner database operations: Firestore for metadata, GCS for raw transcripts."""

import hashlib
import logging
import os
import secrets
from datetime import datetime, timezone

import google.auth
import google.auth.transport.requests
from google.api_core.exceptions import NotFound
from google.cloud import firestore, storage

GCP_PROJECT = os.environ.get("GLEANER_GCP_PROJECT", "covenance-469421")
GCS_BUCKET = os.environ.get("GLEANER_GCS_BUCKET", "gleaner-sessions")
CACHE_TTL_SECONDS = int(os.environ.get("GLEANER_CACHE_TTL", "300"))  # 5 minutes

_db_client = None
_gcs_client = None
_gcs_bucket_obj = None
_cache: dict[str, tuple[float, dict]] = {}  # key -> (expiry_timestamp, data)


def _cache_get(key: str) -> dict | None:
    entry = _cache.get(key)
    if entry and entry[0] > datetime.now(timezone.utc).timestamp():
        return entry[1]
    return None


def _cache_set(key: str, data: dict) -> dict:
    _cache[key] = (datetime.now(timezone.utc).timestamp() + CACHE_TTL_SECONDS, data)
    return data


def _db():
    global _db_client
    if _db_client is None:
        _db_client = firestore.Client(project=GCP_PROJECT)
    return _db_client


def _bucket():
    global _gcs_client, _gcs_bucket_obj
    if _gcs_bucket_obj is None:
        _gcs_client = storage.Client(project=GCP_PROJECT)
        _gcs_bucket_obj = _gcs_client.bucket(GCS_BUCKET)
    return _gcs_bucket_obj


# --- Tokens ---


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_token(name: str, issued_to: str = "", notes: str = "") -> str:
    """Create a new API token. Returns the raw token (shown only once)."""
    token = f"gl_{secrets.token_urlsafe(32)}"
    _db().collection("tokens").document(_token_hash(token)).set(
        {
            "name": name,
            "issued_to": issued_to,
            "notes": notes,
            "prefix": token[:8],
            "active": True,
            "created_at": firestore.SERVER_TIMESTAMP,
            "last_used_at": None,
            "usage_count": 0,
        }
    )
    return token


def validate_token(token: str) -> dict | None:
    """Validate a bearer token. Returns metadata or None."""
    doc_ref = _db().collection("tokens").document(_token_hash(token))
    doc = doc_ref.get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    if not data.get("active"):
        return None
    try:
        doc_ref.update(
            {
                "last_used_at": firestore.SERVER_TIMESTAMP,
                "usage_count": firestore.Increment(1),
            }
        )
    except Exception:
        pass
    return data


def list_tokens() -> list[dict]:
    """List all tokens (without hashes)."""
    tokens = []
    for doc in _db().collection("tokens").stream():
        data = doc.to_dict() or {}
        data["id"] = doc.id
        tokens.append(data)
    return tokens


def revoke_token(id_or_prefix: str) -> bool:
    """Revoke a token by hash ID or prefix."""
    doc_ref = _db().collection("tokens").document(id_or_prefix)
    doc = doc_ref.get()
    if doc.exists:
        doc_ref.update({"active": False})
        return True
    for doc in _db().collection("tokens").stream():
        data = doc.to_dict() or {}
        if data.get("prefix", "").startswith(id_or_prefix):
            doc.reference.update({"active": False})
            return True
    return False


# --- Users ---


def get_user_by_email(email: str) -> dict | None:
    """Get user document by email."""
    doc = _db().collection("users").document(email).get()
    if not doc.exists:
        return None
    return doc.to_dict()


def create_or_update_user(
    email: str, username: str, display_name: str = "", picture: str = ""
) -> dict:
    """Create or update a user. Marks them as onboarded."""
    user_data = {
        "username": username,
        "email": email,
        "display_name": display_name,
        "picture": picture,
        "onboarded": True,
    }
    doc_ref = _db().collection("users").document(email)
    doc = doc_ref.get()
    if doc.exists:
        doc_ref.update(user_data)
    else:
        user_data["created_at"] = firestore.SERVER_TIMESTAMP
        doc_ref.set(user_data)
    return user_data


def is_username_taken(username: str, exclude_email: str = "") -> bool:
    """Check if a username is already in use."""
    for doc in _db().collection("users").stream():
        data = doc.to_dict() or {}
        if data.get("username") == username and doc.id != exclude_email:
            return True
    return False


def list_user_tokens(owner_email: str) -> list[dict]:
    """List tokens owned by a specific user."""
    tokens = []
    for doc in (
        _db().collection("tokens").where("owner_email", "==", owner_email).stream()
    ):
        data = doc.to_dict() or {}
        data["id"] = doc.id
        tokens.append(data)
    return tokens


def create_user_token(username: str, owner_email: str, token_name: str = "") -> str:
    """Create a token for a user. Returns the raw token (shown once)."""
    token = f"gl_{secrets.token_urlsafe(32)}"
    _db().collection("tokens").document(_token_hash(token)).set(
        {
            "name": username,
            "issued_to": owner_email,
            "owner_email": owner_email,
            "notes": token_name or "Dashboard",
            "prefix": token[:8],
            "active": True,
            "created_at": firestore.SERVER_TIMESTAMP,
            "last_used_at": None,
            "usage_count": 0,
        }
    )
    return token


def revoke_user_token(id_or_prefix: str, owner_email: str) -> bool:
    """Revoke a token, verifying ownership."""
    doc_ref = _db().collection("tokens").document(id_or_prefix)
    doc = doc_ref.get()
    if doc.exists and (doc.to_dict() or {}).get("owner_email") == owner_email:
        doc_ref.update({"active": False})
        return True
    for doc in (
        _db().collection("tokens").where("owner_email", "==", owner_email).stream()
    ):
        data = doc.to_dict() or {}
        if data.get("prefix", "").startswith(id_or_prefix):
            doc.reference.update({"active": False})
            return True
    return False


# --- Backup ---


def export_firestore() -> dict:
    """Trigger a Firestore export to GCS. Returns operation info."""
    import urllib.request
    import json

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_uri = f"gs://{GCS_BUCKET}/backups/{stamp}"

    credentials, _ = google.auth.default()
    credentials.refresh(google.auth.transport.requests.Request())

    url = f"https://firestore.googleapis.com/v1/projects/{GCP_PROJECT}/databases/(default):exportDocuments"
    body = json.dumps({
        "outputUriPrefix": output_uri,
        "collectionIds": ["sessions", "tokens"],
    }).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {credentials.token}")
    req.add_header("Content-Type", "application/json")
    resp = urllib.request.urlopen(req, timeout=30)
    result = json.loads(resp.read())
    return {"status": "export_started", "output_uri": output_uri, "operation": result.get("name", "")}


# --- Counters (pre-computed aggregates) ---


def _counter_update(doc_ref, updates: dict):
    """Apply atomic field updates to a counter doc, creating it if needed."""
    try:
        doc_ref.update(updates)
    except NotFound:
        doc_ref.set({})
        doc_ref.update(updates)


def _update_counters(session_id: str, metadata: dict, provenance: dict):
    """Incrementally update counter docs after a session upload."""
    username = provenance.get("user", "")
    project = metadata.get("project", "")
    msg_count = metadata.get("message_count", 0)
    tool_count = metadata.get("tool_use_count", 0)
    tool_counts = metadata.get("tool_counts", {})
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

    # --- Global counters (split across 4 docs to stay under index limits) ---
    counters = _db().collection("counters")

    # Totals + tool usage
    g = {
        "total_sessions": firestore.Increment(1),
        "total_messages": firestore.Increment(msg_count),
        "total_tool_uses": firestore.Increment(tool_count),
    }
    for tool, count in tool_counts.items():
        g[f"tool_usage.{tool}"] = firestore.Increment(count)
    _counter_update(counters.document("global"), g)

    # Daily timeline
    if date_str:
        _counter_update(counters.document("global:daily"), {date_str: firestore.Increment(1)})

    # Per-user rollup
    if username:
        u_rollup = {
            f"{username}.sessions": firestore.Increment(1),
            f"{username}.messages": firestore.Increment(msg_count),
            f"{username}.tool_uses": firestore.Increment(tool_count),
            f"{username}.total_duration_seconds": firestore.Increment(duration),
        }
        if first_ts:
            u_rollup[f"{username}.last_active"] = first_ts
        _counter_update(counters.document("global:users"), u_rollup)

    # Per-project rollup
    if project:
        p_rollup = {
            f"{project}.sessions": firestore.Increment(1),
            f"{project}.messages": firestore.Increment(msg_count),
        }
        if username:
            p_rollup[f"{project}.users"] = firestore.ArrayUnion([username])
        _counter_update(counters.document("global:projects"), p_rollup)

    # --- User counter ---
    if username:
        u = {
            "total_sessions": firestore.Increment(1),
            "total_messages": firestore.Increment(msg_count),
            "total_tool_uses": firestore.Increment(tool_count),
            "total_duration_seconds": firestore.Increment(duration),
            "last_session_id": session_id,
            "last_active": first_ts or "",
        }
        for tool, count in tool_counts.items():
            u[f"tool_usage.{tool}"] = firestore.Increment(count)
        if project:
            u[f"project_usage.{project}"] = firestore.Increment(1)
        if date_str:
            u[f"daily.{date_str}.s"] = firestore.Increment(1)
            u[f"daily.{date_str}.m"] = firestore.Increment(msg_count)
            u[f"daily.{date_str}.d"] = firestore.Increment(duration)

        _counter_update(_db().collection("counters").document(f"user:{username}"), u)


def _recent_sessions(user: str | None = None, limit: int = 10) -> list[dict]:
    """Fetch recent sessions with a simple limit query (no full scan)."""
    query = _db().collection("sessions")
    if user:
        query = query.where("provenance.user", "==", user)
    query = query.order_by("uploaded_at", direction=firestore.Query.DESCENDING).limit(limit)

    results = []
    for doc in query.stream():
        data = doc.to_dict() or {}
        results.append({
            "session_id": doc.id,
            "topic": data.get("topic", ""),
            "project": data.get("project", ""),
            "cwd": data.get("cwd", ""),
            "user": data.get("provenance", {}).get("user", ""),
            "message_count": data.get("message_count", 0),
            "tool_use_count": data.get("tool_use_count", 0),
            "first_timestamp": data.get("first_timestamp"),
            "last_timestamp": data.get("last_timestamp"),
            "provenance": data.get("provenance", {}),
            "transcript_size": data.get("transcript_size", 0),
        })
    return results


# --- Sessions ---


def store_session(
    session_id: str,
    metadata: dict,
    provenance: dict,
    transcript_gz: bytes,
    transcript_size: int,
):
    """Store session metadata in Firestore and raw transcript in GCS."""
    # Upload gzipped transcript to GCS
    blob = _bucket().blob(f"sessions/{session_id}.jsonl.gz")
    blob.upload_from_string(transcript_gz, content_type="application/gzip")

    # Store metadata in Firestore
    doc_data = {
        **metadata,
        "provenance": provenance,
        "transcript_size": transcript_size,
        "transcript_gz_size": len(transcript_gz),
        "gcs_path": f"sessions/{session_id}.jsonl.gz",
        "uploaded_at": firestore.SERVER_TIMESTAMP,
    }
    _db().collection("sessions").document(session_id).set(doc_data)

    try:
        _update_counters(session_id, metadata, provenance)
    except Exception as e:
        logging.warning("Counter update failed for session %s: %s", session_id, e)

    # Invalidate caches so next read reflects the new session
    _cache.pop("global_stats", None)
    if provenance.get("user"):
        _cache.pop(f"user_stats:{provenance['user']}", None)


def get_session(session_id: str) -> dict | None:
    """Get session metadata from Firestore."""
    doc = _db().collection("sessions").document(session_id).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    data["session_id"] = doc.id
    return data


def get_session_transcript(session_id: str) -> bytes | None:
    """Download raw gzipped transcript from GCS."""
    blob = _bucket().blob(f"sessions/{session_id}.jsonl.gz")
    if not blob.exists():
        return None
    return blob.download_as_bytes()


def list_sessions(
    user: str | None = None,
    project: str | None = None,
    limit: int = 100,
    ids_only: bool = False,
) -> list:
    """List sessions, optionally filtered."""
    query = _db().collection("sessions")

    if user:
        query = query.where("provenance.user", "==", user)
    if project:
        query = query.where("project", "==", project)

    query = query.order_by("uploaded_at", direction=firestore.Query.DESCENDING)
    query = query.limit(limit)

    if ids_only:
        return [doc.id for doc in query.stream()]

    results = []
    for doc in query.stream():
        data = doc.to_dict() or {}
        data["session_id"] = doc.id
        # Don't include large fields in list view
        data.pop("tool_counts", None)
        # Keep topic for session list display
        results.append(data)
    return results


def get_user_stats(username: str) -> dict:
    """Personal stats for a single user: last session, weekly stats, heatmap, rhythm."""
    cached = _cache_get(f"user_stats:{username}")
    if cached:
        return cached
    return _cache_set(f"user_stats:{username}", _compute_user_stats(username))


def _compute_user_stats(username: str) -> dict:
    """Read from user counter doc + limited queries. No full scan."""
    from collections import defaultdict
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    today = now.date()
    week_start = today - timedelta(days=today.weekday())  # Monday
    prev_week_start = week_start - timedelta(days=7)
    heatmap_start = (today.replace(day=1) - timedelta(days=90)).replace(day=1)
    week_start_str = week_start.isoformat()
    prev_week_start_str = prev_week_start.isoformat()

    # 1 document read
    doc = _db().collection("counters").document(f"user:{username}").get()
    if not doc.exists:
        return {
            "user": username, "total_sessions": 0, "avg_messages_per_session": 0,
            "last_session": None, "week_stats": {
                "sessions": 0, "sessions_prev_week": 0, "messages": 0,
                "avg_duration_seconds": 0, "total_duration_seconds": 0,
                "active_days": 0, "most_active_project": "",
            },
            "heatmap": [], "tool_usage": {}, "project_usage": {}, "recent_sessions": [],
        }

    u = doc.to_dict()
    daily = u.get("daily", {})

    # Week / prev-week stats from daily map
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

    # Heatmap from daily map
    heatmap_list = []
    d = heatmap_start
    while d <= today:
        ds = d.isoformat()
        day_data = daily.get(ds, {})
        count = day_data.get("s", 0) if isinstance(day_data, dict) else 0
        heatmap_list.append({"date": ds, "count": count})
        d += timedelta(days=1)

    # Recent sessions: limit query (~10 doc reads)
    recent = _recent_sessions(user=username, limit=20)

    # Most active project this week: from the recent sessions we already fetched
    week_projects: dict[str, int] = defaultdict(int)
    for s in recent:
        ts = s.get("first_timestamp", "") or ""
        if ts[:10] >= week_start_str:
            proj = s.get("project", "")
            if proj:
                week_projects[proj] += 1
    most_active = max(week_projects, key=week_projects.get) if week_projects else ""

    # Last session: single doc read
    last_session_id = u.get("last_session_id", "")
    last_session = get_session(last_session_id) if last_session_id else None

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
    """Aggregate stats across all sessions."""
    cached = _cache_get("global_stats")
    if cached:
        return cached
    return _cache_set("global_stats", _compute_stats())


def _compute_stats() -> dict:
    """Read from global counter + user counters + limited query. No full scan."""
    from datetime import timedelta

    counters = _db().collection("counters")
    empty = {
        "total_sessions": 0, "total_messages": 0, "total_tool_uses": 0,
        "unique_users": 0, "unique_projects": 0, "avg_duration_seconds": 0,
        "active_this_week": 0, "users": [], "projects": [],
        "tool_usage": {}, "timeline": [], "user_stats": {},
        "project_stats": {}, "recent_sessions": [],
    }

    # Read 4 split counter docs
    refs = [counters.document(n) for n in ("global", "global:daily", "global:users", "global:projects")]
    docs = {doc.id: doc.to_dict() for doc in _db().get_all(refs) if doc.exists}
    g = docs.get("global")
    if not g:
        return empty

    users_map = docs.get("global:users", {})
    projects_map = docs.get("global:projects", {})
    daily_map = docs.get("global:daily", {})

    # Batch-read user counters for enrichment (top_project, active_days_this_week)
    user_refs = [_db().collection("counters").document(f"user:{u}") for u in users_map]
    user_counters = {}
    if user_refs:
        for udoc in _db().get_all(user_refs):
            if udoc.exists:
                # doc id is "user:username"
                uname = udoc.id.split(":", 1)[1] if ":" in udoc.id else udoc.id
                user_counters[uname] = udoc.to_dict()

    today = datetime.now(timezone.utc).date()
    week_start_str = (today - timedelta(days=today.weekday())).isoformat()

    # Build user_stats from global users map + user counters
    user_stats = {}
    active_this_week = 0
    for username, info in users_map.items():
        sessions = info.get("sessions", 0)
        dur = info.get("total_duration_seconds", 0)

        uc = user_counters.get(username, {})
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

    # Build project_stats from global projects map
    project_stats = {}
    for name, info in projects_map.items():
        project_stats[name] = {
            "sessions": info.get("sessions", 0),
            "messages": info.get("messages", 0),
            "users": sorted(info.get("users", [])),
        }
    sorted_project_stats = dict(sorted(project_stats.items(), key=lambda x: -x[1]["sessions"])[:15])

    # Timeline from daily map (last 30 days)
    timeline = []
    for i in range(29, -1, -1):
        day = (today - timedelta(days=i)).isoformat()
        timeline.append({"date": day, "count": daily_map.get(day, 0)})

    # Recent sessions: limit query (~10 doc reads)
    recent_sessions = _recent_sessions(limit=10)

    # Avg duration across all users
    total_dur = sum(info.get("total_duration_seconds", 0) for info in users_map.values())
    total_sess = g.get("total_sessions", 0)
    avg_duration = round(total_dur / total_sess) if total_sess else 0

    return {
        "total_sessions": total_sess,
        "total_messages": g.get("total_messages", 0),
        "total_tool_uses": g.get("total_tool_uses", 0),
        "unique_users": len(users_map),
        "unique_projects": len(projects_map),
        "avg_duration_seconds": avg_duration,
        "active_this_week": active_this_week,
        "users": sorted(users_map.keys()),
        "projects": sorted(projects_map.keys()),
        "tool_usage": dict(sorted(g.get("tool_usage", {}).items(), key=lambda x: -x[1])),
        "timeline": timeline,
        "user_stats": sorted_user_stats,
        "project_stats": sorted_project_stats,
        "recent_sessions": recent_sessions,
    }
