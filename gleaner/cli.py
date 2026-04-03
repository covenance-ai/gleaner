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

from gleaner.config import (
    CLAUDE_SETTINGS,
    CONFIG_FILE,
    CURSOR_HOOKS,
    get_credentials,
    install_backfill_agent,
    install_cursor_hook,
    install_hook,
    is_backfill_agent_installed,
    is_cursor_hook_installed,
    is_hook_installed,
    read_config,
    remove_backfill_agent,
    remove_cursor_hook,
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
        print(f"  Claude  hook installed in {CLAUDE_SETTINGS}")
    else:
        print(f"  Claude  hook already in {CLAUDE_SETTINGS}")

    if install_cursor_hook():
        print(f"  Cursor  hook installed in {CURSOR_HOOKS}")
    else:
        print(f"  Cursor  hook already in {CURSOR_HOOKS}")

    if install_backfill_agent():
        print(f"  Sync    cursor backfill agent started (every 5 min)")
    else:
        print(f"  Sync    cursor backfill agent already running")

    user = _check_server(args.url, args.token)
    if user:
        print(f"  Auth    connected as {user}")
    else:
        print(f"  Auth    could not verify — check URL and token")

    print("\nDone. New sessions will upload automatically.")


def cmd_status(args):
    url, token = get_credentials()

    print("Gleaner\n")

    if CONFIG_FILE.exists():
        print(f"  Config  {CONFIG_FILE}")
    else:
        src = "env" if url else "not configured"
        print(f"  Config  {src}")

    print(f"  URL     {url or '—'}")
    print(f"  Token   {token[:8]}..." if token else "  Token   —")
    print(f"  Claude  hook {'enabled' if is_hook_installed() else 'disabled'}")
    print(f"  Cursor  hook {'enabled' if is_cursor_hook_installed() else 'disabled'}")
    print(f"  Sync    {'running' if is_backfill_agent_installed() else 'stopped'}")

    if url and token:
        user = _check_server(url, token)
        print(f"  Auth    {user}" if user else "  Auth    failed")
    print()


def cmd_on(args):
    claude_new = install_hook()
    cursor_new = install_cursor_hook()
    backfill_new = install_backfill_agent()
    if claude_new or cursor_new or backfill_new:
        print("Hooks enabled")
    else:
        print("Hooks already enabled")


def cmd_off(args):
    claude_removed = remove_hook()
    cursor_removed = remove_cursor_hook()
    backfill_removed = remove_backfill_agent()
    if claude_removed or cursor_removed or backfill_removed:
        print("Hooks disabled")
    else:
        print("Hooks not installed")


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
    p.add_argument(
        "--source",
        choices=["claude", "cursor"],
        default="claude",
        help="Session source (default: claude)",
    )

    sub.add_parser("collect", help="Collect local IDE sessions into the vault")

    p = sub.add_parser("serve", help="Start local dashboard")
    p.add_argument("--port", type=int, default=8765, help="Port (default: 8765)")
    p.add_argument("--no-collect", action="store_true", help="Skip session collection on startup")

    p = sub.add_parser("pull", help="Download sessions for local analysis")
    p.add_argument("-o", "--output", help="Output directory (default: ~/.gleaner)")
    p.add_argument("--transcripts", action="store_true", help="Also download raw transcripts")
    p.add_argument("-j", "--workers", type=int, default=4, help="Parallel downloads")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands: dict = {
        "setup": cmd_setup,
        "status": cmd_status,
        "on": cmd_on,
        "off": cmd_off,
        "auth": cmd_auth,
    }

    if args.command == "serve":
        try:
            import uvicorn  # noqa: F401
        except ImportError:
            print("uvicorn + fastapi required: pip install 'gleaner[serve]'", file=sys.stderr)
            sys.exit(1)

        if not args.no_collect:
            try:
                import pyarrow  # noqa: F401
                from gleaner.vault import collect
                added = collect()
                if added:
                    print(f"Collected {added} new sessions")
            except ImportError:
                print("pyarrow not installed, skipping collect", file=sys.stderr)

        import os
        os.environ["GLEANER_LOCAL"] = "1"
        import uvicorn
        print(f"Starting local dashboard at http://127.0.0.1:{args.port}")
        uvicorn.run("server.server:app", host="127.0.0.1", port=args.port)
        sys.exit(0)

    elif args.command == "collect":
        try:
            import pyarrow  # noqa: F401
        except ImportError:
            print("pyarrow required: pip install 'gleaner[pull]'", file=sys.stderr)
            sys.exit(1)

        from gleaner.vault import VAULT_DIR, collect

        added = collect()
        index = VAULT_DIR / "index.parquet"
        total = 0
        if index.exists():
            import pyarrow.parquet as pq

            total = pq.read_metadata(index).num_rows
        if added:
            print(f"Collected {added} new sessions (total: {total})")
        else:
            print(f"Up to date ({total} sessions)")
    elif args.command == "backfill":
        from gleaner.backfill import run

        run(dry_run=args.dry_run, project=args.project, force=args.force, source=args.source)
    elif args.command == "pull":
        from gleaner.pull import run as pull_run

        pull_run(output=args.output, transcripts=args.transcripts, workers=args.workers)
    else:
        commands[args.command](args)


if __name__ == "__main__":
    main()
