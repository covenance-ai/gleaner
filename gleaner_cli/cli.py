"""Gleaner CLI: setup, status, and hook management.

Usage:
    gleaner setup URL TOKEN    Configure and install the session hook
    gleaner status             Show current configuration
    gleaner on                 Enable the session upload hook
    gleaner off                Disable the session upload hook
    gleaner auth TOKEN         Update the API token
    gleaner backfill           Upload existing sessions
"""

import argparse
import json
import sys
import urllib.request

from gleaner_cli.config import (
    CLAUDE_SETTINGS,
    CONFIG_FILE,
    get_credentials,
    install_hook,
    is_hook_installed,
    read_config,
    remove_hook,
    write_config,
)


def _check_server(url: str, token: str) -> str | None:
    """Verify connection. Returns username or None."""
    try:
        req = urllib.request.Request(f"{url.rstrip('/')}/api/me")
        req.add_header("Authorization", f"Bearer {token}")
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        return data.get("user")
    except Exception:
        return None


def cmd_setup(args):
    write_config(args.url, args.token)
    print(f"  Config  saved to {CONFIG_FILE}")

    if install_hook():
        print(f"  Hook    installed in {CLAUDE_SETTINGS}")
    else:
        print(f"  Hook    already in {CLAUDE_SETTINGS}")

    user = _check_server(args.url, args.token)
    if user:
        print(f"  Auth    connected as {user}")
    else:
        print(f"  Auth    could not verify — check URL and token")

    print("\nDone. New Claude Code sessions will upload automatically.")


def cmd_status(args):
    url, token = get_credentials()
    hook = is_hook_installed()

    print("Gleaner\n")

    if CONFIG_FILE.exists():
        print(f"  Config  {CONFIG_FILE}")
    else:
        src = "env" if url else "not configured"
        print(f"  Config  {src}")

    print(f"  URL     {url or '—'}")
    print(f"  Token   {token[:8]}..." if token else "  Token   —")
    print(f"  Hook    {'enabled' if hook else 'disabled'}")

    if url and token:
        user = _check_server(url, token)
        print(f"  Auth    {user}" if user else "  Auth    failed")
    print()


def cmd_on(args):
    if install_hook():
        print("Hook enabled")
    else:
        print("Hook already enabled")


def cmd_off(args):
    if remove_hook():
        print("Hook disabled")
    else:
        print("Hook not installed")


def cmd_auth(args):
    cfg = read_config()
    url = cfg.get("url", "")
    if not url:
        print("Run 'gleaner setup URL TOKEN' first", file=sys.stderr)
        sys.exit(1)
    write_config(url, args.token)
    print(f"Token updated ({args.token[:8]}...)")

    user = _check_server(url, args.token)
    if user:
        print(f"Connected as {user}")
    else:
        print("Could not verify — check the token")


def main():
    parser = argparse.ArgumentParser(prog="gleaner", description="Gleaner CLI")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("setup", help="Configure Gleaner and install the session hook")
    p.add_argument("url", help="Gleaner server URL")
    p.add_argument("token", help="API token (gl_...)")

    sub.add_parser("status", help="Show configuration status")
    sub.add_parser("on", help="Enable the session upload hook")
    sub.add_parser("off", help="Disable the session upload hook")

    p = sub.add_parser("auth", help="Update the API token")
    p.add_argument("token", help="New API token (gl_...)")

    p = sub.add_parser("backfill", help="Upload existing sessions to Gleaner")
    p.add_argument("--dry-run", action="store_true", help="List without uploading")
    p.add_argument("--project", type=str, help="Filter by project name")
    p.add_argument("--force", action="store_true", help="Re-upload existing")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "setup": cmd_setup,
        "status": cmd_status,
        "on": cmd_on,
        "off": cmd_off,
        "auth": cmd_auth,
    }

    if args.command == "backfill":
        from gleaner_cli.backfill import run

        run(dry_run=args.dry_run, project=args.project, force=args.force)
    else:
        commands[args.command](args)


if __name__ == "__main__":
    main()
