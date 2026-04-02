# Gleaner

Harvest and centralize Claude Code session transcripts across your team.

Gleaner automatically uploads complete session transcripts to central storage when a session ends. It gives your team visibility into how Claude Code is being used: which tools, which projects, how often, and the full conversation history.

https://gleaner-430011644943.europe-west1.run.app/gleaner/

## Quick start

```bash
# Install the CLI (requires uv: https://docs.astral.sh/uv)
uv tool install git+https://github.com/covenance-ai/gleaner

# Configure and install the session hook
gleaner setup https://gleaner-430011644943.europe-west1.run.app gl_your_token

# Check everything is working
gleaner status
```

That's it. Every Claude Code session auto-uploads from now on.

Get a token by signing in with Google at your Gleaner dashboard.

## CLI commands

```bash
gleaner setup URL TOKEN     # Save config + install session hook
gleaner status              # Show config, hook, and connection status
gleaner on                  # Enable the session upload hook
gleaner off                 # Disable the session upload hook
gleaner auth TOKEN          # Update the API token
gleaner backfill            # Upload existing sessions from ~/.claude/projects/
gleaner backfill --dry-run  # Preview what would be uploaded
```

Config is stored in `~/.config/gleaner.json`. The session hook is managed in `~/.claude/settings.json`.

## How it works

```
Claude Code session ends
        |
        v
SessionEnd hook fires (gleaner-upload)
        |
        v
  - finds the session JSONL in ~/.claude/projects/
  - parses metadata (message counts, tools used, duration)
  - optionally scrubs PII/secrets
  - uploads metadata to Firestore + raw transcript to GCS
```

Claude Code records full session transcripts locally as JSONL files. Gleaner collects these centrally so you can browse, search, and analyze them across your whole team.

## Dashboard

The web dashboard is available at your Gleaner URL. Sign in with Google to onboard, or use a `gl_` token.

Features:
- **Home**: personal stats, activity heatmap, recent sessions
- **Team**: aggregate stats, member activity, project breakdown
- **Sessions**: filterable list with full transcript viewer and search
- **Settings**: token management, setup instructions

## Deploy the server

The server deploys to Cloud Run automatically on push to `main` via GitHub Actions.

For manual initial setup:

```bash
# Set required env vars on Cloud Run
gcloud run services update gleaner --region europe-west1 \
    --update-env-vars "GLEANER_ADMIN_TOKEN=$(openssl rand -hex 32)" \
    --update-env-vars "GLEANER_GOOGLE_CLIENT_ID=your-oauth-client-id"
```

The admin token is for the `/admin/*` API (bulk token management). The Google client ID enables the "Sign in with Google" button for user onboarding.

## API

All data endpoints require a `Bearer` token (user token or Google JWT).

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/session` | Bearer | Upload a session transcript |
| `GET` | `/api/sessions` | Bearer | List sessions (filter: `?user=`, `?project=`, `?limit=`) |
| `GET` | `/api/session/{id}` | Bearer | Session metadata |
| `GET` | `/api/session/{id}/raw` | Bearer | Download raw JSONL.gz |
| `GET` | `/api/me` | Bearer/Google | Personal stats or onboarding status |
| `GET` | `/api/stats` | Bearer | Aggregate usage stats |
| `POST` | `/api/onboard` | Google | Complete user onboarding |
| `POST` | `/api/tokens` | Bearer | Create own API token |
| `GET` | `/api/tokens` | Bearer | List own tokens |
| `DELETE` | `/api/tokens/{id}` | Bearer | Revoke own token |
| `POST` | `/admin/tokens` | Admin | Create token for any user |
| `GET` | `/admin/tokens` | Admin | List all tokens |

## Project structure

```
gleaner/
  gleaner/              # Installable client package
    cli.py                  # gleaner command: setup, status, on/off, auth
    upload.py               # gleaner-upload: SessionEnd hook handler
    backfill.py             # gleaner backfill: upload existing sessions
    config.py               # Config file + Claude settings.json management
    scrub.py                # PII/secret scrubbing (optional deps)
  server/                   # FastAPI server (deployed to Cloud Run)
    server.py               # API routes and auth
    db.py                   # Firestore + GCS operations
    db_mock.py              # In-memory mock for dev/testing
    dashboard.html          # Single-file SPA dashboard
    Dockerfile
    requirements.txt
  ops/                      # Operational scripts (run manually)
    backfill_counters.py    # Rebuild counter docs from sessions
    backfill_topics.py      # Extract topics from transcripts
    scrub_cloud.py          # Scrub all transcripts in GCS
  tests/
    test_e2e.py             # Upload-and-retrieve integration tests
    test_scrub.py           # PII scrubbing unit tests
  .github/workflows/
    deploy.yml              # CI: test + deploy to Cloud Run on push
  pyproject.toml
```

## Architecture

```
Developer machine                        GCP (covenance-469421)
+------------------+                     +----------------------------+
| Claude Code      |                     | Cloud Run (gleaner)        |
|  SessionEnd hook |--POST /api/session->| FastAPI server             |
|  gleaner-upload  |                     |   |           |            |
+------------------+                     |   v           v            |
                                         | Firestore   GCS            |
+------------------+                     | (metadata)  (transcripts)  |
| Web browser      |--GET /api/sessions->|   |           |            |
| Dashboard        |<--JSON/HTML---------|   v           v            |
+------------------+                     | sessions/   sessions/      |
                                         | users/      {id}.jsonl.gz  |
                                         | tokens/                    |
                                         +----------------------------+
```

## Environment variables

**Server-side** (Cloud Run):

| Variable | Default | Description |
|----------|---------|-------------|
| `GLEANER_GCP_PROJECT` | `covenance-469421` | GCP project ID |
| `GLEANER_GCS_BUCKET` | `gleaner-sessions` | GCS bucket for transcripts |
| `GLEANER_ADMIN_TOKEN` | (none) | Admin token for `/admin/*` endpoints |
| `GLEANER_GOOGLE_CLIENT_ID` | (none) | Google OAuth client ID for sign-in |
| `BASE_PATH` | `/gleaner` | URL prefix |
| `PORT` | `8080` | HTTP listen port |
