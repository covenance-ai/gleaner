# Maitre — Enrichment Feasibility

## Realistic & Promising

| Feature | Effort | Value | Notes |
|---|---|---|---|
| Diff-based outcome tracking | Low | High | Track file changes, test pass/fail, reverts — objective signal, no user input needed |
| Auto-tagging (language, framework, task type) | Low | Medium | Cheap to extract from existing context; improves retrieval |
| Token/cost tracking per session | Trivial | Medium | People actively want this; easy sell |
| One-click user rating (binary or 1-5) | Low | High | Devs will do one click, won't fill forms. Binary is fine |
| Local full-text search over sessions | Low-Med | High | "Find that thing I solved 3 weeks ago" — turns principle into tool |
| Combined auto-tags + ratings → filtered queries | Medium | High | e.g. "all failed Rust debugging sessions" — pattern visibility without analytics |

## Challenges & Roadblocks

| Challenge | Severity | Detail |
|---|---|---|
| Deferred value proposition | High | Users agree it's smart but don't install — the flossing problem |
| Platform adapter maintenance | High | Each platform (Cursor, Claude Code, OpenCode, Copilot) structures sessions differently; N adapters, N keeps growing |
| Session boundary definition | Medium | Agentic flows span multiple tool calls, edits, rollbacks — "what is one session?" is a real design problem |
| Structured vs raw tradeoff | Medium | Too shallow (raw logs) = no better than scrolling up. Too deep = maintenance burden |
| Platform incumbents shipping built-in | High | Cursor has history, Claude Code has `/history` — a good-enough built-in kills third-party overnight |
| LLM-based enrichment costs | Medium | Any auto-summarization via LLM call costs money/latency for a tool meant to be passive |
| Scope creep toward analytics | Low-Med | Useful data without a query layer = hoarding on faith; building the layer = you're now an analytics product |
