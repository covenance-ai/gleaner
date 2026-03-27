"""Tests for the Gleaner API server using FastAPI TestClient.

All tests run in mock mode (GLEANER_MOCK=1) so no Firestore/GCS/Google
OAuth is needed. The mock DB is seeded with sample data at import time.
"""

import base64
import gzip
import json
import os

import pytest
from fastapi.testclient import TestClient

# conftest.py sets GLEANER_MOCK=1 and adds server/ to sys.path
from server import _suggest_username, app

client = TestClient(app, root_path="/gleaner")
AUTH = {"Authorization": "Bearer mock"}


class TestSuggestUsername:
    """_suggest_username derives a valid username from email/name."""

    def test_from_email(self):
        assert _suggest_username("alice@example.com") == "alice"

    def test_dots_become_hyphens(self):
        assert _suggest_username("john.doe@company.com") == "john-doe"

    def test_strips_invalid_chars(self):
        # + is stripped (not a dot), ü is stripped
        assert _suggest_username("über+user@x.com") == "beruser"

    def test_two_char_email_prefix_is_valid(self):
        # "ab" is already 2 chars — no fallback needed
        assert _suggest_username("ab@x.com", "Alice Bob") == "ab"

    def test_truncates_to_20(self):
        assert len(_suggest_username("a" * 30 + "@x.com")) <= 20

    def test_very_short_falls_back(self):
        assert _suggest_username("@x.com", "A") == "user"


class TestPublicEndpoints:
    def test_health(self):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_config(self):
        r = client.get("/api/config")
        assert r.status_code == 200
        data = r.json()
        assert "mock" in data
        assert data["mock"] is True

    def test_dashboard(self):
        r = client.get("/")
        assert r.status_code == 200
        assert "Gleaner" in r.text



class TestAuth:
    """Auth validation with MOCK_MODE disabled — uses real token lookup against mock DB."""

    VALID_TOKEN = "gl_mock_local_dev_token_1234567890abcdef"  # seeded in db_mock

    @pytest.fixture(autouse=True)
    def disable_mock_mode(self, monkeypatch):
        import server
        monkeypatch.setattr(server, "MOCK_MODE", False)

    def test_no_header_returns_401(self):
        r = client.get("/api/me")
        assert r.status_code == 401

    def test_invalid_token_returns_403(self):
        r = client.get("/api/me", headers={"Authorization": "Bearer gl_bad_token"})
        assert r.status_code == 403

    def test_valid_token_returns_200(self):
        r = client.get("/api/me", headers={"Authorization": f"Bearer {self.VALID_TOKEN}"})
        assert r.status_code == 200
        assert r.json()["user"] == "ikamen"

    def test_malformed_header_returns_401(self):
        r = client.get("/api/sessions", headers={"Authorization": "Token abc"})
        assert r.status_code == 401

    def test_revoked_token_returns_403(self):
        """Create a token, revoke it, then try to use it."""
        import db_mock as db
        raw = db.create_user_token("testuser", "test@x.com", "to-revoke")
        db.revoke_user_token(raw[:8], "test@x.com")
        r = client.get("/api/me", headers={"Authorization": f"Bearer {raw}"})
        assert r.status_code == 403


class TestMeEndpoint:
    def test_returns_user_stats(self):
        r = client.get("/api/me", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert "user" in data
        assert "total_sessions" in data


class TestStatsEndpoint:
    def test_returns_aggregate_stats(self):
        r = client.get("/api/stats", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert "total_sessions" in data
        assert "total_messages" in data
        assert data["total_sessions"] > 0


class TestSessionUploadAndRetrieve:
    """Upload a session and verify it can be retrieved with correct metadata."""

    @pytest.fixture(autouse=True)
    def upload_session(self):
        """Upload a synthetic session for subsequent tests."""
        transcript_lines = [
            json.dumps({
                "type": "user",
                "timestamp": "2026-03-20T10:00:00Z",
                "message": {"content": "Test session for API"},
            }),
            json.dumps({
                "type": "assistant",
                "timestamp": "2026-03-20T10:00:05Z",
                "message": {"content": [
                    {"type": "text", "text": "Response."},
                    {"type": "tool_use", "id": "t1", "name": "Read", "input": {}},
                ]},
            }),
        ]
        raw = "\n".join(transcript_lines).encode()
        gz = gzip.compress(raw)

        self.session_id = "test-api-session-001"
        payload = {
            "session_id": self.session_id,
            "metadata": {
                "session_id": self.session_id,
                "message_count": 2,
                "user_message_count": 1,
                "assistant_message_count": 1,
                "tool_use_count": 1,
                "tool_counts": {"Read": 1},
                "first_timestamp": "2026-03-20T10:00:00Z",
                "last_timestamp": "2026-03-20T10:00:05Z",
                "topic": "Test session for API",
                "project": "test-project",
                "cwd": "/tmp/test",
            },
            "provenance": {"user": "testuser", "host": "ci", "platform": "Linux x86_64"},
            "transcript_size": len(raw),
            "transcript_gz_b64": base64.b64encode(gz).decode(),
        }
        r = client.post("/api/session", json=payload, headers=AUTH)
        assert r.status_code == 200

    def test_session_in_list(self):
        r = client.get("/api/sessions?limit=100", headers=AUTH)
        ids = [s["session_id"] for s in r.json()["sessions"]]
        assert self.session_id in ids

    def test_get_metadata(self):
        r = client.get(f"/api/session/{self.session_id}", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["topic"] == "Test session for API"
        assert data["message_count"] == 2
        assert data["tool_counts"]["Read"] == 1

    def test_download_raw_roundtrip(self):
        """Downloaded gzipped transcript decompresses to valid JSONL."""
        r = client.get(f"/api/session/{self.session_id}/raw", headers=AUTH)
        assert r.status_code == 200
        raw = gzip.decompress(r.content)
        lines = [json.loads(l) for l in raw.decode().strip().split("\n")]
        assert len(lines) == 2
        assert lines[0]["type"] == "user"

    def test_ids_only(self):
        r = client.get("/api/sessions?ids_only=true", headers=AUTH)
        assert self.session_id in r.json()["session_ids"]


class TestUsernameCheck:
    def test_available(self):
        r = client.get("/api/username-check/freshname99", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["available"] is True

    def test_taken(self):
        """alice exists in mock seed data."""
        r = client.get("/api/username-check/alice", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["available"] is False

    def test_invalid_format(self):
        r = client.get("/api/username-check/-bad", headers=AUTH)
        assert r.json()["available"] is False


class TestSelfServiceTokens:
    """Users can create, list, and revoke their own tokens."""

    def test_create_token(self):
        r = client.post("/api/tokens", json={"name": "ci-test"}, headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["token"].startswith("gl_")
        assert data["prefix"].startswith("gl_")

    def test_list_tokens(self):
        # Create one first
        client.post("/api/tokens", json={"name": "list-test"}, headers=AUTH)
        r = client.get("/api/tokens", headers=AUTH)
        assert r.status_code == 200
        tokens = r.json()["tokens"]
        assert any(t["notes"] == "list-test" for t in tokens)

    def test_revoke_token(self):
        r = client.post("/api/tokens", json={"name": "revoke-me"}, headers=AUTH)
        prefix = r.json()["prefix"]
        # Find the token id
        tokens = client.get("/api/tokens", headers=AUTH).json()["tokens"]
        tok = next(t for t in tokens if t["prefix"] == prefix)

        r = client.delete(f"/api/tokens/{tok['id']}", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["status"] == "revoked"

    def test_revoke_nonexistent(self):
        r = client.delete("/api/tokens/doesnotexist", headers=AUTH)
        assert r.status_code == 404


class TestSessionFilters:
    def test_filter_by_user(self):
        r = client.get("/api/sessions?user=ikamen&limit=5", headers=AUTH)
        assert r.status_code == 200
        for s in r.json()["sessions"]:
            assert s.get("provenance", {}).get("user") == "ikamen"

    def test_filter_by_project(self):
        """Filtering by project returns only matching sessions."""
        r = client.get("/api/sessions?limit=100", headers=AUTH)
        all_projects = {s["project"] for s in r.json()["sessions"]}
        if all_projects:
            proj = next(iter(all_projects))
            r2 = client.get(f"/api/sessions?project={proj}&limit=100", headers=AUTH)
            for s in r2.json()["sessions"]:
                assert s["project"] == proj


class TestUserProfile:
    def test_get_user_stats(self):
        r = client.get("/api/user/ikamen/stats", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["user"] == "ikamen"
        assert "total_sessions" in data
