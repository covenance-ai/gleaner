"""Gleaner API server: receives and serves Claude Code session transcripts.

Endpoints:
    POST /api/session              Upload a session transcript (Bearer auth)
    GET  /api/sessions             List sessions, filterable (Bearer auth)
    GET  /api/sessions?ids_only=true  List session IDs only (for backfill dedup)
    GET  /api/session/{id}         Get session metadata (Bearer auth)
    GET  /api/session/{id}/raw     Download raw JSONL transcript (Bearer auth)
    GET  /api/me                   Personal stats / onboarding status (Bearer or Google auth)
    GET  /api/stats                Aggregate usage stats (Bearer auth)
    POST /api/onboard              Complete user onboarding (Google auth)
    GET  /api/username-check/{u}   Check username availability (Google auth)
    POST /api/tokens               Create own API token (Bearer auth)
    GET  /api/tokens               List own API tokens (Bearer auth)
    DELETE /api/tokens/{id}        Revoke own API token (Bearer auth)
    POST /admin/tokens             Create API token (Admin auth)
    GET  /admin/tokens             List tokens (Admin auth)
    DELETE /admin/tokens/{id}      Revoke a token (Admin auth)
    POST /admin/backup             Trigger Firestore export to GCS (Admin auth)
    GET  /api/health               Health check (public)
"""

import base64
import os
import re
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token as google_id_token

if os.environ.get("GLEANER_MOCK"):
    import db_mock as db
else:
    import db

_server_dir = Path(__file__).parent
_JS_FILES = ["util", "api", "auth", "onboarding", "home", "team", "sessions", "settings", "app"]
_js = "\n".join((_server_dir / "js" / f"{name}.js").read_text() for name in _JS_FILES)
DASHBOARD_HTML = (
    (_server_dir / "dashboard.html")
    .read_text()
    .replace("/* {STYLES} */", (_server_dir / "dashboard.css").read_text())
    .replace("/* {SCRIPT} */", _js)
)

ADMIN_TOKEN = os.environ.get("GLEANER_ADMIN_TOKEN", "")
BASE_PATH = os.environ.get("BASE_PATH", "/gleaner")
GOOGLE_CLIENT_ID = os.environ.get("GLEANER_GOOGLE_CLIENT_ID", "")
ALLOWED_USERS: dict[str, str] = {}  # email -> username
for _pair in filter(None, os.environ.get("GLEANER_ALLOWED_USERS", "").split(",")):
    if ":" in _pair:
        _e, _u = _pair.strip().split(":", 1)
        ALLOWED_USERS[_e.strip()] = _u.strip()

app = FastAPI(
    title="Gleaner",
    description="Claude Code session transcript collector",
    root_path=BASE_PATH,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,18}[a-z0-9]$")


def _suggest_username(email: str, display_name: str = "") -> str:
    """Suggest a username from email or display name."""
    local = email.split("@")[0] if "@" in email else email
    username = re.sub(r"[^a-z0-9_-]", "", local.replace(".", "-")).lower()
    if len(username) < 2:
        username = re.sub(r"[^a-z0-9_-]", "", display_name.replace(" ", "-")).lower()
    if len(username) < 2:
        username = "user"
    return username[:20]


def _verify_google_jwt(token: str) -> dict | None:
    if not GOOGLE_CLIENT_ID:
        return None
    try:
        idinfo = google_id_token.verify_oauth2_token(
            token, google_auth_requests.Request(), GOOGLE_CLIENT_ID
        )
        email = idinfo.get("email", "")
        if not email:
            return None

        # Backward compat: if ALLOWED_USERS is configured, use it
        if ALLOWED_USERS:
            username = ALLOWED_USERS.get(email)
            if not username:
                return None
            return {
                "name": username,
                "email": email,
                "display_name": idinfo.get("name", ""),
                "picture": idinfo.get("picture", ""),
                "auth_type": "google",
                "active": True,
            }

        # Self-service: look up user in database
        user = db.get_user_by_email(email)
        if user and user.get("onboarded"):
            return {
                "name": user["username"],
                "email": email,
                "display_name": user.get("display_name") or idinfo.get("name", ""),
                "picture": user.get("picture") or idinfo.get("picture", ""),
                "auth_type": "google",
                "active": True,
            }

        # New or non-onboarded user
        return {
            "name": "",
            "email": email,
            "display_name": idinfo.get("name", ""),
            "picture": idinfo.get("picture", ""),
            "auth_type": "google",
            "active": True,
            "onboarding_required": True,
            "suggested_username": _suggest_username(email, idinfo.get("name", "")),
        }
    except Exception:
        return None


MOCK_MODE = bool(os.environ.get("GLEANER_MOCK"))
_MOCK_USER = {"name": "ikamen", "active": True, "email": "ikamen@example.com"}


def _require_token(authorization: str = Header("")) -> dict:
    """Authenticate. Rejects non-onboarded Google users."""
    if MOCK_MODE:
        return _MOCK_USER
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Bearer token")
    token = authorization[7:]
    token_data = db.validate_token(token)
    if token_data:
        return token_data
    google_data = _verify_google_jwt(token)
    if google_data:
        if google_data.get("onboarding_required"):
            raise HTTPException(403, "Onboarding required")
        return google_data
    raise HTTPException(403, "Invalid or revoked token")


def _require_token_allow_onboarding(authorization: str = Header("")) -> dict:
    """Authenticate, allowing non-onboarded Google users through."""
    if MOCK_MODE:
        return _MOCK_USER
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Bearer token")
    token = authorization[7:]
    token_data = db.validate_token(token)
    if token_data:
        return token_data
    google_data = _verify_google_jwt(token)
    if google_data:
        return google_data
    raise HTTPException(403, "Invalid or revoked token")


def _require_admin(authorization: str = Header("")):
    if not ADMIN_TOKEN:
        raise HTTPException(500, "Admin token not configured")
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(403, "Invalid admin token")


# --- Public ---


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return DASHBOARD_HTML


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "gleaner"}


@app.get("/api/config")
def get_config():
    return {"google_client_id": GOOGLE_CLIENT_ID, "mock": MOCK_MODE}


# --- Session endpoints (Bearer auth) ---


@app.post("/api/session")
async def upload_session(request: Request, authorization: str = Header("")):
    token_data = _require_token(authorization)
    body = await request.json()

    session_id = body.get("session_id")
    if not session_id:
        raise HTTPException(400, "session_id required")

    metadata = body.get("metadata", {})
    provenance = body.get("provenance", {})
    # Server is authority on user identity, not the client
    provenance["user"] = token_data.get("name", provenance.get("user", ""))
    transcript_size = body.get("transcript_size", 0)

    # Decode the gzipped transcript
    gz_b64 = body.get("transcript_gz_b64", "")
    if not gz_b64:
        raise HTTPException(400, "transcript_gz_b64 required")
    transcript_gz = base64.b64decode(gz_b64)

    db.store_session(session_id, metadata, provenance, transcript_gz, transcript_size)
    return {"status": "ok", "session_id": session_id}


@app.get("/api/sessions")
def list_sessions(
    user: str | None = None,
    project: str | None = None,
    limit: int = 100,
    ids_only: bool = False,
    since: str | None = None,
    export: bool = False,
    authorization: str = Header(""),
):
    _require_token(authorization)

    uploaded_after = None
    if since:
        from datetime import datetime as _dt
        # URL decoding turns '+' into ' ' in timezone offsets; normalize both forms
        normalized = since.replace("Z", "+00:00").replace(" 00:00", "+00:00")
        uploaded_after = _dt.fromisoformat(normalized)

    if ids_only:
        session_ids = db.list_sessions(
            user=user, project=project, limit=limit, ids_only=True,
            uploaded_after=uploaded_after,
        )
        return {"session_ids": session_ids}

    sessions = db.list_sessions(
        user=user, project=project, limit=limit,
        uploaded_after=uploaded_after, keep_tool_counts=export,
    )
    return {"sessions": sessions}


@app.get("/api/session/{session_id}")
def get_session(session_id: str, authorization: str = Header("")):
    _require_token(authorization)
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return session


@app.get("/api/session/{session_id}/raw")
def get_session_raw(session_id: str, authorization: str = Header("")):
    _require_token(authorization)
    data = db.get_session_transcript(session_id)
    if data is None:
        raise HTTPException(404, "Transcript not found")
    return Response(
        content=data,
        media_type="application/gzip",
        headers={"Content-Disposition": f"attachment; filename={session_id}.jsonl.gz"},
    )


@app.get("/api/me")
def get_me(authorization: str = Header("")):
    token_data = _require_token_allow_onboarding(authorization)

    if token_data.get("onboarding_required"):
        return {
            "onboarding_required": True,
            "email": token_data.get("email", ""),
            "suggested_username": token_data.get("suggested_username", ""),
            "display_name": token_data.get("display_name", ""),
            "picture": token_data.get("picture", ""),
        }

    username = token_data.get("name", "")
    if not username:
        raise HTTPException(400, "Token has no name — cannot determine user identity")
    stats = db.get_user_stats(username)
    if token_data.get("auth_type") == "google":
        stats["email"] = token_data.get("email", "")
        stats["display_name"] = token_data.get("display_name", "")
        stats["picture"] = token_data.get("picture", "")
    return stats


@app.get("/api/user/{username}/stats")
def get_user_profile(username: str, authorization: str = Header("")):
    _require_token(authorization)
    return db.get_user_stats(username)


@app.get("/api/stats")
def get_stats(authorization: str = Header("")):
    _require_token(authorization)
    return db.get_stats()


# --- Onboarding & self-service tokens ---


@app.post("/api/onboard")
async def onboard(request: Request, authorization: str = Header("")):
    """Complete user onboarding: set username, create user record."""
    token_data = _require_token_allow_onboarding(authorization)
    email = token_data.get("email", "")
    if not email or token_data.get("auth_type") != "google":
        raise HTTPException(400, "Google authentication required for onboarding")

    body = await request.json()
    username = body.get("username", "").strip().lower()

    if not USERNAME_RE.match(username):
        raise HTTPException(
            400, "Username must be 2-20 chars: lowercase letters, numbers, hyphens, underscores"
        )

    if db.is_username_taken(username, exclude_email=email):
        raise HTTPException(409, "Username already taken")

    user = db.create_or_update_user(
        email=email,
        username=username,
        display_name=token_data.get("display_name", ""),
        picture=token_data.get("picture", ""),
    )
    return {"user": user}


@app.get("/api/username-check/{username}")
def check_username(username: str, authorization: str = Header("")):
    token_data = _require_token_allow_onboarding(authorization)
    email = token_data.get("email", "")
    username = username.strip().lower()

    if not USERNAME_RE.match(username):
        return {"available": False, "reason": "Invalid format"}
    taken = db.is_username_taken(username, exclude_email=email)
    return {"available": not taken}


def _get_user_email(token_data: dict) -> str:
    email = token_data.get("email") or token_data.get("owner_email") or token_data.get("issued_to", "")
    if not email or "@" not in email:
        raise HTTPException(400, "Sign in with Google to manage tokens")
    return email


@app.post("/api/tokens")
async def create_my_token(request: Request, authorization: str = Header("")):
    """Create an API token for the authenticated user."""
    token_data = _require_token(authorization)
    email = _get_user_email(token_data)
    username = token_data.get("name", "")

    body = await request.json()
    token_name = body.get("name", "")

    raw_token = db.create_user_token(
        username=username, owner_email=email, token_name=token_name
    )
    return {"token": raw_token, "name": token_name, "prefix": raw_token[:8]}


@app.get("/api/tokens")
def list_my_tokens(authorization: str = Header("")):
    """List the authenticated user's tokens."""
    token_data = _require_token(authorization)
    email = _get_user_email(token_data)
    return {"tokens": db.list_user_tokens(email)}


@app.delete("/api/tokens/{id_or_prefix}")
def revoke_my_token(id_or_prefix: str, authorization: str = Header("")):
    """Revoke one of the authenticated user's tokens."""
    token_data = _require_token(authorization)
    email = _get_user_email(token_data)
    if db.revoke_user_token(id_or_prefix, email):
        return {"status": "revoked"}
    raise HTTPException(404, "Token not found")


# --- Admin endpoints ---


@app.post("/admin/tokens")
async def create_token(request: Request, authorization: str = Header("")):
    _require_admin(authorization)
    body = await request.json()
    name = body.get("name", "")
    if not name:
        raise HTTPException(400, "name required")
    token = db.create_token(
        name=name,
        issued_to=body.get("issued_to", ""),
        notes=body.get("notes", ""),
    )
    return {"token": token, "name": name}


@app.get("/admin/tokens")
def admin_list_tokens(authorization: str = Header("")):
    _require_admin(authorization)
    return {"tokens": db.list_tokens()}


@app.delete("/admin/tokens/{id_or_prefix}")
def admin_revoke_token(id_or_prefix: str, authorization: str = Header("")):
    _require_admin(authorization)
    if db.revoke_token(id_or_prefix):
        return {"status": "revoked"}
    raise HTTPException(404, "Token not found")


@app.post("/admin/backup")
def admin_backup(authorization: str = Header("")):
    _require_admin(authorization)
    try:
        return db.export_firestore()
    except Exception as e:
        raise HTTPException(500, f"Backup failed: {e}")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
