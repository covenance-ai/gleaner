"""Vault data schema.

Defines the canonical formats for the local session vault:

    ~/.gleaner/
    ├── index.parquet                    ← SessionMeta rows
    └── sessions/{session_id}/
        ├── raw.jsonl                    ← original IDE format (not modeled)
        └── transcript.jsonl             ← NormalizedEntry lines

These models are the source of truth for what the vault stores.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class NormalizedEntry(BaseModel):
    """One line in transcript.jsonl.

    Unifies Claude Code (type/timestamp) and Cursor (role/no timestamp)
    into a single shape. Content blocks are passed through from the IDE
    without further normalization.
    """

    role: Literal["user", "assistant", "unknown"]
    ts: str | None = None
    content: list[dict[str, Any]]


class SessionMeta(BaseModel):
    """One row in index.parquet — metadata for a vault session.

    Produced by ingest_session() at collection time. Fields are chosen
    to support filtering, grouping, and basic analytics via
    pd.read_parquet("~/.gleaner/index.parquet").
    """

    session_id: str
    ide: Literal["claude_code", "cursor"]
    project: str
    topic: str
    cwd: str

    # classification (from gleaner.tags)
    source: Literal["human", "kodo", "test"]
    task_type: str

    # provenance
    user: str
    host: str
    platform: str

    # counts
    message_count: int
    user_message_count: int
    assistant_message_count: int
    tool_use_count: int
    tool_counts_json: str  # JSON-encoded {tool_name: count}

    # time range
    first_timestamp: str
    last_timestamp: str

    # storage
    transcript_size: int  # raw file bytes
    ingested_at: str  # ISO 8601 UTC
    origin: Literal["local", "cloud"]
