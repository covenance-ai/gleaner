"""Gleaner configuration: config file, Claude Code and Cursor hook management."""

import json
import os
import plistlib
import shutil
import subprocess
from pathlib import Path

CONFIG_FILE = Path.home() / ".config" / "gleaner.json"
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
CURSOR_HOOKS = Path.home() / ".cursor" / "hooks.json"
LAUNCHD_LABEL = "com.gleaner.cursor-backfill"
LAUNCHD_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
BACKFILL_INTERVAL = 300  # seconds

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


# -- Cursor hook management ----------------------------------------------------


def read_cursor_hooks() -> dict:
    if not CURSOR_HOOKS.exists():
        return {}
    try:
        return json.loads(CURSOR_HOOKS.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def write_cursor_hooks(hooks: dict):
    CURSOR_HOOKS.parent.mkdir(parents=True, exist_ok=True)
    CURSOR_HOOKS.write_text(json.dumps(hooks, indent=2) + "\n")


def is_cursor_hook_installed() -> bool:
    cfg = read_cursor_hooks()
    for entry in cfg.get("hooks", {}).get("stop", []):
        if "gleaner" in entry.get("command", ""):
            return True
    return False


def install_cursor_hook() -> bool:
    """Add gleaner-cursor-upload to Cursor stop hooks. Returns True if newly added."""
    if is_cursor_hook_installed():
        return False
    cfg = read_cursor_hooks()
    cfg["version"] = 1
    cfg.setdefault("hooks", {})
    cfg["hooks"].setdefault("stop", [])
    cfg["hooks"]["stop"].append({"command": "gleaner-cursor-upload"})
    write_cursor_hooks(cfg)
    return True


def remove_cursor_hook() -> bool:
    """Remove gleaner-cursor-upload from Cursor stop hooks. Returns True if removed."""
    cfg = read_cursor_hooks()
    stop = cfg.get("hooks", {}).get("stop", [])
    filtered = [e for e in stop if "gleaner" not in e.get("command", "")]
    if len(filtered) == len(stop):
        return False
    cfg["hooks"]["stop"] = filtered
    write_cursor_hooks(cfg)
    return True


# -- Periodic Cursor backfill (launchd) ----------------------------------------


def _backfill_command() -> str:
    """Find the gleaner-backfill executable path."""
    path = shutil.which("gleaner-backfill")
    if path:
        return path
    # Fall back to the same directory as the current Python
    import sys
    candidate = Path(sys.executable).parent / "gleaner-backfill"
    if candidate.exists():
        return str(candidate)
    return "gleaner-backfill"


def is_backfill_agent_installed() -> bool:
    return LAUNCHD_PLIST.exists()


def install_backfill_agent() -> bool:
    """Install a launchd agent that runs cursor backfill periodically."""
    if LAUNCHD_PLIST.exists():
        return False

    plist = {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": [_backfill_command(), "--source", "cursor"],
        "StartInterval": BACKFILL_INTERVAL,
        "StandardOutPath": str(Path.home() / ".gleaner" / "backfill.log"),
        "StandardErrorPath": str(Path.home() / ".gleaner" / "backfill.log"),
        "RunAtLoad": True,
    }

    LAUNCHD_PLIST.parent.mkdir(parents=True, exist_ok=True)
    (Path.home() / ".gleaner").mkdir(parents=True, exist_ok=True)
    LAUNCHD_PLIST.write_bytes(plistlib.dumps(plist))
    subprocess.run(["launchctl", "load", str(LAUNCHD_PLIST)], capture_output=True)
    return True


def remove_backfill_agent() -> bool:
    """Unload and remove the launchd backfill agent."""
    if not LAUNCHD_PLIST.exists():
        return False
    subprocess.run(["launchctl", "unload", str(LAUNCHD_PLIST)], capture_output=True)
    LAUNCHD_PLIST.unlink()
    return True
