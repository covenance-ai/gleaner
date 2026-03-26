# Gleaner

Harvest and centralize Claude Code session transcripts across your team.

Gleaner is a Claude Code plugin that automatically uploads complete session transcripts to central storage when a session ends. It gives your team visibility into how Claude Code is being used: which tools, which projects, how often, and the full conversation history.

## How it works

```
Claude Code session ends
        |
        v
SessionEnd hook fires
        |
        v
upload-session.py
  - finds the session JSONL in ~/.claude/projects/
  - parses metadata (message counts, tools used, duration)
  - uploads metadata to Firestore + raw transcript to GCS
```

Claude Code already records full session transcripts locally as JSONL files (used by `--resume`). Each JSONL file contains every user message, assistant response, tool call with full input, and tool result with full output. Gleaner collects these centrally so you can browse, search, and analyze them across your whole team.

## Install the plugin

```bash
# From the Claude Code plugin marketplace (once published):
/plugin install gleaner

# Or during development, run Claude Code with:
claude --plugin-dir /path/to/gleaner
```

Then set environment variables (add to your shell profile):

```bash
export GLEANER_URL="https://covenance-469421.web.app/gleaner"
export GLEANER_TOKEN="gl_your_token_here"
```

That's it. Every session auto-uploads from now on.

## Upload existing sessions

Backfill all your past Claude Code sessions:

```bash
# See what would be uploaded
python3 scripts/backfill.py --dry-run

# Upload everything
python3 scripts/backfill.py

# Only a specific project
python3 scripts/backfill.py --project my-project

# Re-upload sessions that are already on the server
python3 scripts/backfill.py --force
```

The backfill script deduplicates automatically — it checks the server for existing session IDs before uploading.

## Dashboard

The web dashboard is available at your Gleaner URL (e.g. `https://covenance-469421.web.app/gleaner/`). Sign in with your `gl_` token.

Features:
- **Overview**: total sessions, messages, tool uses, unique users and projects
- **Tool usage chart**: see which tools (Bash, Edit, Read, etc.) are used most across all sessions
- **Session browser**: filterable list of all sessions by user and project
- **Session detail**: per-session metadata, tool breakdown, and full transcript viewer with user prompts, assistant responses, tool calls (with full input), and tool results (with full output)
- **Light/dark mode**: toggle between themes, respects system preference by default

## Deploy the server

Prerequisites: `gcloud` CLI authenticated with the GCP project.

```bash
cd server
bash deploy.sh
```

This creates:
- A Cloud Run service (`gleaner`) in `europe-west1`
- A GCS bucket (`gleaner-sessions`) for raw transcripts
- Firestore collections for metadata and tokens

After the initial deploy, disable the IAM invoker check so the API is reachable:

```bash
gcloud run services update gleaner --region europe-west1 --no-invoker-iam-check
```

Then set an admin token and create user tokens:

```bash
# Set admin token
ADMIN_TOKEN=$(openssl rand -hex 32)
gcloud run services update gleaner --region europe-west1 \
    --update-env-vars "GLEANER_ADMIN_TOKEN=$ADMIN_TOKEN"

# Create a user token
curl -X POST "https://covenance-469421.web.app/gleaner/admin/tokens" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"name": "alice", "issued_to": "alice@team.com"}'
# Returns: {"token": "gl_...", "name": "alice"}
```

Save the admin token securely. User tokens are shown only once at creation time.

### Firebase Hosting (optional)

If you want a clean URL (e.g. `your-project.web.app/gleaner/`), add a rewrite to your `firebase.json`:

```json
{
  "hosting": {
    "rewrites": [
      {
        "source": "/gleaner/**",
        "run": { "serviceId": "gleaner", "region": "europe-west1" }
      }
    ]
  }
}
```

Then `firebase deploy --only hosting`.

## API

All data endpoints require a `Bearer` token in the `Authorization` header.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/` | Public | Web dashboard |
| `GET` | `/api/health` | Public | Health check |
| `POST` | `/api/session` | Bearer | Upload a session transcript |
| `GET` | `/api/sessions` | Bearer | List sessions (filter: `?user=`, `?project=`, `?limit=`, `?ids_only=true`) |
| `GET` | `/api/session/{id}` | Bearer | Session metadata |
| `GET` | `/api/session/{id}/raw` | Bearer | Download raw JSONL.gz |
| `GET` | `/api/stats` | Bearer | Aggregate usage stats |
| `POST` | `/admin/tokens` | Admin | Create token (`{"name": "...", "issued_to": "...", "notes": "..."}`) |
| `GET` | `/admin/tokens` | Admin | List all tokens |
| `DELETE` | `/admin/tokens/{id}` | Admin | Revoke a token |

## What data is collected

Each uploaded session includes:

**Metadata** (stored in Firestore, queryable):
- Session ID, project name, working directory
- Message counts (total, user, assistant)
- Tool usage counts (total + per-tool breakdown)
- First and last timestamps
- Transcript size

**Provenance** (auto-collected):
- Username, hostname, platform (e.g. "Darwin arm64")

**Raw transcript** (stored in GCS as gzipped JSONL):
- Every user message (full text)
- Every assistant response (full text)
- Every tool call (tool name + full input parameters)
- Every tool result (full output)
- Session lifecycle events (queue operations, etc.)

## Security

- **GCS bucket**: public access prevention enforced, uniform bucket-level access, no anonymous access
- **Firestore**: accessible only via GCP IAM (project members)
- **API tokens**: stored as SHA-256 hashes in Firestore — raw tokens are never stored and shown only once at creation
- **Token entropy**: `gl_` prefix + 32 bytes of URL-safe random = computationally infeasible to brute-force
- **Transport**: HTTPS enforced by Cloud Run
- **No direct GCS URLs**: transcripts are only accessible through the authenticated API

## Architecture

```
Team member's machine                     GCP (covenance-469421)
+------------------+                      +----------------------------+
| Claude Code      |                      | Cloud Run (gleaner)        |
|  SessionEnd hook |---POST /api/session->| FastAPI server             |
|  upload-session  |                      |   |           |            |
+------------------+                      |   v           v            |
                                          | Firestore   GCS            |
+------------------+                      | (metadata)  (transcripts)  |
| Web browser      |---GET /api/sessions->|   |           |            |
| Dashboard        |<--JSON/HTML----------|   v           v            |
+------------------+                      | sessions/   sessions/      |
                                          | {id}        {id}.jsonl.gz  |
                                          +----------------------------+
```

- **Storage**: Firestore (session metadata, tokens) + GCS (raw transcripts)
- **Compute**: Cloud Run, FastAPI, scales to zero
- **Auth**: SHA-256 hashed bearer tokens in Firestore
- **GCP project**: `covenance-469421`, region `europe-west1`

## Project structure

```
gleaner/
  .claude-plugin/
    plugin.json               # Claude Code plugin manifest
  hooks/
    hooks.json                # SessionEnd hook registration
  scripts/
    upload-session.py         # Hook script (runs on SessionEnd)
    upload_session_lib.py     # Shared upload/parse library
    backfill.py               # Upload existing sessions from disk
  server/
    server.py                 # FastAPI application
    db.py                     # Firestore + GCS operations
    dashboard.html            # Single-file SPA dashboard
    requirements.txt          # Python dependencies
    Dockerfile                # Container image
    deploy.sh                 # One-command Cloud Run deployment
  README.md
```

## Environment variables

**Client-side** (team members):
| Variable | Description |
|----------|-------------|
| `GLEANER_URL` | Base URL of the Gleaner API |
| `GLEANER_TOKEN` | Bearer token for authentication |

**Server-side** (Cloud Run):
| Variable | Default | Description |
|----------|---------|-------------|
| `GLEANER_GCP_PROJECT` | `covenance-469421` | GCP project ID |
| `GLEANER_GCS_BUCKET` | `gleaner-sessions` | GCS bucket for transcripts |
| `GLEANER_ADMIN_TOKEN` | (none) | Admin token for token management |
| `BASE_PATH` | `/gleaner` | URL prefix (for reverse proxy / Firebase Hosting) |
| `PORT` | `8080` | HTTP listen port |
