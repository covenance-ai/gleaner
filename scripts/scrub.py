"""Scrub PII and secrets from text before upload.

Reuses the approach from kodo's trace_upload module:
- piicleaner for PII detection (credit cards, emails, phone numbers, etc.)
- detect-secrets for API keys, tokens, passwords
- Regex for assignment-style secrets (API_KEY=value, secret: value)
"""

from __future__ import annotations

import logging
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger(__name__)

_SECRET_ASSIGNMENT_RE = re.compile(
    r"""(?ix)
    (?P<prefix>
        (?:["'])?
        (?P<key>[a-z0-9_.-]*(?:api[_-]?key|secret|token|password|passwd|private[_-]?key|access[_-]?key)[a-z0-9_.-]*)
        (?:["'])?
        \s*(?P<sep>=|:)\s*
    )
    (?P<quote>["'])?
    (?P<value>[^"',\s}]+)
    (?P=quote)?
    """
)

_pii_cleaner = None


@dataclass(frozen=True)
class ScrubStats:
    redactions: int = 0

    def __add__(self, other: ScrubStats) -> ScrubStats:
        return ScrubStats(redactions=self.redactions + other.redactions)


def _get_pii_cleaner():
    global _pii_cleaner
    if _pii_cleaner is None:
        from piicleaner import Cleaner

        _pii_cleaner = Cleaner()
    return _pii_cleaner


def _scrub_pii(text: str) -> tuple[str, int]:
    cleaner = _get_pii_cleaner()
    matches = cleaner.detect_pii(text)
    if not matches:
        return text, 0
    return cleaner.clean_pii(text, "redact"), len(matches)


def _scrub_secrets(text: str) -> tuple[str, int]:
    from detect_secrets.core import scan
    from detect_secrets.settings import default_settings

    redactions = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        sample = Path(tmpdir) / "archive.txt"
        sample.write_text(text, encoding="utf-8")
        with default_settings():
            secrets = {
                finding.secret_value
                for finding in scan.scan_file(str(sample))
                if getattr(finding, "secret_value", "")
            }

    for secret in sorted(secrets, key=len, reverse=True):
        count = text.count(secret)
        if count:
            redactions += count
            text = text.replace(secret, "[secret-redacted]")

    def redact_assignment(match: re.Match[str]) -> str:
        quote = match.group("quote") or ""
        return f"{match.group('prefix')}{quote}[secret-redacted]{quote}"

    text, assignment_count = _SECRET_ASSIGNMENT_RE.subn(redact_assignment, text)
    return text, redactions + assignment_count


def scrub_text(text: str) -> tuple[str, ScrubStats]:
    """Scrub secrets and PII from text. Returns (scrubbed_text, stats)."""
    try:
        text, secret_redactions = _scrub_secrets(text)
        text, pii_redactions = _scrub_pii(text)
        total = secret_redactions + pii_redactions
        if total:
            _log.info("Scrubbed %d sensitive item(s) from transcript", total)
        return text, ScrubStats(redactions=total)
    except Exception as exc:
        _log.warning("Scrubbing failed (uploading as-is): %s", exc)
        return text, ScrubStats()
