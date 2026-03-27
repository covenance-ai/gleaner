"""Gleaner configuration: config file and Claude Code hook management."""

import json
import os
from pathlib import Path

CONFIG_FILE = Path.home() / ".config" / "gleaner.json"
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"

HOOK_ENTRY = {
    "hooks": [
        {
            "type": "command",
            "command": "gleaner-upload",
            "timeout": 30,
        }
    ]
}


def read_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def write_config(url: str, token: str):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps({"url": url, "token": token}, indent=2) + "\n")


def get_credentials() -> tuple[str, str]:
    """Get URL and token from env vars (preferred) or config file (fallback)."""
    url = os.environ.get("GLEANER_URL", "")
    token = os.environ.get("GLEANER_TOKEN", "")
    if url and token:
        return url, token
    cfg = read_config()
    return url or cfg.get("url", ""), token or cfg.get("token", "")


def read_claude_settings() -> dict:
    if not CLAUDE_SETTINGS.exists():
        return {}
    try:
        return json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def write_claude_settings(settings: dict):
    CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    CLAUDE_SETTINGS.write_text(json.dumps(settings, indent=2) + "\n")


def is_hook_installed() -> bool:
    settings = read_claude_settings()
    for group in settings.get("hooks", {}).get("SessionEnd", []):
        for hook in group.get("hooks", []):
            if "gleaner" in hook.get("command", ""):
                return True
    return False


def install_hook() -> bool:
    """Add gleaner-upload to SessionEnd hooks. Returns True if newly added."""
    if is_hook_installed():
        return False
    settings = read_claude_settings()
    settings.setdefault("hooks", {})
    settings["hooks"].setdefault("SessionEnd", [])
    settings["hooks"]["SessionEnd"].append(HOOK_ENTRY)
    write_claude_settings(settings)
    return True


def remove_hook() -> bool:
    """Remove gleaner-upload from SessionEnd hooks. Returns True if removed."""
    settings = read_claude_settings()
    session_end = settings.get("hooks", {}).get("SessionEnd", [])
    filtered = [
        group
        for group in session_end
        if not any("gleaner" in h.get("command", "") for h in group.get("hooks", []))
    ]
    if len(filtered) == len(session_end):
        return False
    settings["hooks"]["SessionEnd"] = filtered
    write_claude_settings(settings)
    return True
