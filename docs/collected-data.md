# What Data Gleaner Collects

## Transcript content

Each Claude Code session produces a JSONL file. Gleaner uploads the **entire file**
after scrubbing PII/secrets. The JSONL contains:

| Content type | Present? | Example |
|---|---|---|
| User messages | Full text | Every prompt typed by the user |
| Assistant replies | Full text | All of Claude's responses |
| Tool inputs | Full | Tool name + parameters (file path, bash command, search pattern, …) |
| Tool results | Full | File contents from Read, command stdout/stderr from Bash, Grep matches, etc. |
| Thinking traces | No | Claude Code does not write extended-thinking tokens to JSONL |
| Images / binary | No | Only text representations appear |

**Source code exposure**: when Claude reads a file via the Read tool, the full file
content appears as a tool result in the transcript and is uploaded.

## Scrubbing (before upload)

Runs client-side (`scrub_text()`), so raw data never leaves the machine.

**Engine**: Presidio (default) or legacy regex fallback.

Detected and replaced with `[secret-redacted]` / `[pii-redacted]`:

- API keys, tokens, passwords (pattern: `api_key`, `secret`, `token`, `password`, …)
- PEM private keys
- Bearer tokens (20+ char)
- Connection strings (postgres/mysql/mongodb/redis/amqp URIs)
- AWS access keys (`AKIA…`)
- GitHub tokens (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`)
- Credit cards, SSNs, IBANs, passports, phone numbers, emails, IP addresses

## Extracted metadata

Stored in Firestore as a document per session (`sessions/{session_id}`):

```
session_id          string     UUID
topic               string     First user message, truncated to 200 chars
project             string     Directory name from Claude Code project path
cwd                 string     Working directory at session start
message_count       int        Total JSONL lines
user_message_count  int        Lines with type=user
assistant_message_count int    Lines with type=assistant
tool_use_count      int        Total tool invocations
tool_counts         map        Per-tool breakdown, e.g. {"Bash": 3, "Read": 5}
first_timestamp     timestamp  Earliest message timestamp
last_timestamp      timestamp  Latest message timestamp
transcript_size     int        Uncompressed transcript bytes
transcript_gz_size  int        Gzipped transcript bytes
redactions          int        Number of PII/secret replacements made
source              string     "human", "kodo", or "test" (auto-classified)
task_type           string     "development", "swe_bench", "commit", etc.
provenance.user     string     OS username (overridden by token identity)
provenance.host     string     Hostname
provenance.platform string     e.g. "Darwin arm64"
uploaded_at         timestamp  Server-side upload time
```

## Storage

Firestore is a NoSQL document database — each session is a nested dict
keyed by `session_id`, no schema enforced, no joins.

- **Metadata** → Firestore document (`sessions/{session_id}`)
- **Full transcript** → GCS blob (`sessions/{session_id}.jsonl.gz`)
- **Aggregates** → Firestore `counters` collection (pre-computed stats)

See `DATA_STORAGE.md` in project root for the full storage architecture diagram.

## Filtering

Sessions are skipped (not uploaded) when:
- No user messages
- No assistant messages
- All assistant messages are rate-limit errors ("hit your limit")
