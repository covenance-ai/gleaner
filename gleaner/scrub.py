"""Scrub PII and secrets from text before upload.

Two backends, selected via GLEANER_SCRUB_ENGINE env var:
  "legacy"   — piicleaner + detect-secrets + regex (default)
  "presidio" — Microsoft Presidio with spaCy NER + custom secret recognizers

Set GLEANER_SCRUB_ENGINE=presidio to opt in to the new backend.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger(__name__)

SCRUB_ENGINE = os.environ.get("GLEANER_SCRUB_ENGINE", "legacy")

_REDACTED = "[secret-redacted]"
_PII_REDACTED = "[pii-redacted]"

# --- Shared regex patterns (used by both backends) ---

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

_PEM_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]+(?:PRIVATE KEY|KEY BLOCK)-----"
    r"[\s\S]*?"
    r"-----END [A-Z0-9 ]+(?:PRIVATE KEY|KEY BLOCK)-----"
)


@dataclass(frozen=True)
class ScrubStats:
    redactions: int = 0

    def __add__(self, other: ScrubStats) -> ScrubStats:
        return ScrubStats(redactions=self.redactions + other.redactions)


# =============================================================================
# Legacy backend (piicleaner + detect-secrets)
# =============================================================================

_pii_cleaner = None


def _get_pii_cleaner():
    global _pii_cleaner
    if _pii_cleaner is None:
        from piicleaner import Cleaner

        _pii_cleaner = Cleaner()
    return _pii_cleaner


def _legacy_scrub_pii(text: str) -> tuple[str, int]:
    cleaner = _get_pii_cleaner()
    matches = cleaner.detect_pii(text)
    if not matches:
        return text, 0
    return cleaner.clean_pii(text, "redact"), len(matches)


def _legacy_scrub_secrets(text: str) -> tuple[str, int]:
    from detect_secrets.core import scan
    from detect_secrets.settings import default_settings

    redactions = 0

    # PEM blocks first — detect-secrets only catches the header, not the body.
    text, pem_count = _PEM_BLOCK_RE.subn(_REDACTED, text)
    redactions += pem_count

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
            text = text.replace(secret, _REDACTED)

    def redact_assignment(match: re.Match[str]) -> str:
        quote = match.group("quote") or ""
        return f"{match.group('prefix')}{quote}{_REDACTED}{quote}"

    text, assignment_count = _SECRET_ASSIGNMENT_RE.subn(redact_assignment, text)
    redactions += assignment_count

    return text, redactions


def _legacy_scrub(text: str) -> tuple[str, int]:
    text, secret_redactions = _legacy_scrub_secrets(text)
    text, pii_redactions = _legacy_scrub_pii(text)
    return text, secret_redactions + pii_redactions


# =============================================================================
# Presidio backend
# =============================================================================

_presidio_analyzer = None
_presidio_engine = None


def _get_presidio():
    """Lazy-init Presidio analyzer with custom secret recognizers."""
    global _presidio_analyzer, _presidio_engine
    if _presidio_analyzer is not None:
        return _presidio_analyzer, _presidio_engine

    from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
    from presidio_anonymizer import AnonymizerEngine

    # Custom recognizers for secrets that Presidio doesn't cover
    secret_patterns = [
        PatternRecognizer(
            supported_entity="SECRET_KEY",
            name="assignment_secret",
            patterns=[Pattern(
                "assignment",
                # \\? handles JSON-escaped quotes (\" in JSONL)
                r"(?i)(?:api[_-]?key|secret|token|password|passwd|private[_-]?key|access[_-]?key)\s*[=:]\s*\\?[\"']?([^\"',\s}\\]{8,})",
                0.9,
            )],
        ),
        PatternRecognizer(
            supported_entity="PEM_KEY",
            name="pem_block",
            patterns=[Pattern(
                "pem",
                r"-----BEGIN [A-Z0-9 ]+(?:PRIVATE KEY|KEY BLOCK)-----[\s\S]*?-----END [A-Z0-9 ]+(?:PRIVATE KEY|KEY BLOCK)-----",
                1.0,
            )],
        ),
        PatternRecognizer(
            supported_entity="BEARER_TOKEN",
            name="bearer_auth",
            patterns=[Pattern(
                "bearer",
                r"(?i)(?:Authorization:\s*Bearer\s+|Bearer\s+)([A-Za-z0-9_\-\.]{20,})",
                0.85,
            )],
        ),
        PatternRecognizer(
            supported_entity="CONNECTION_STRING",
            name="connection_string",
            patterns=[Pattern(
                "connstr",
                r"(?:postgres|mysql|mongodb|redis|amqp)(?:ql)?://[^\s,\"'}{]+",
                0.9,
            )],
        ),
        PatternRecognizer(
            supported_entity="AWS_KEY",
            name="aws_access_key",
            patterns=[Pattern("aws", r"AKIA[0-9A-Z]{16}", 0.95)],
        ),
        PatternRecognizer(
            supported_entity="GITHUB_TOKEN",
            name="github_token",
            patterns=[Pattern(
                "ghp",
                r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}",
                0.95,
            )],
        ),
    ]

    analyzer = AnalyzerEngine()
    for recognizer in secret_patterns:
        analyzer.registry.add_recognizer(recognizer)

    engine = AnonymizerEngine()

    _presidio_analyzer = analyzer
    _presidio_engine = engine
    return analyzer, engine


# Entity types worth redacting in code transcripts.
# Excludes DATE_TIME (timestamps are structural), URL (file paths get caught),
# NRP, US_DRIVER_LICENSE, and other low-signal types that cause false positives.
_PRESIDIO_ENTITIES = [
    # PII
    "CREDIT_CARD", "CRYPTO", "EMAIL_ADDRESS", "IBAN_CODE", "IP_ADDRESS",
    "PERSON", "PHONE_NUMBER", "US_SSN", "US_PASSPORT", "US_BANK_NUMBER",
    "MEDICAL_LICENSE", "US_ITIN",
    # Custom secrets
    "SECRET_KEY", "PEM_KEY", "BEARER_TOKEN", "CONNECTION_STRING",
    "AWS_KEY", "GITHUB_TOKEN",
]

_PRESIDIO_SCORE_THRESHOLD = 0.5


def _presidio_scrub(text: str) -> tuple[str, int]:
    from presidio_anonymizer.entities import OperatorConfig

    analyzer, engine = _get_presidio()

    results = analyzer.analyze(
        text=text,
        language="en",
        entities=_PRESIDIO_ENTITIES,
        score_threshold=_PRESIDIO_SCORE_THRESHOLD,
    )
    if not results:
        return text, 0

    anonymized = engine.anonymize(
        text=text,
        analyzer_results=results,
        operators={
            "DEFAULT": OperatorConfig("replace", {"new_value": _PII_REDACTED}),
            "SECRET_KEY": OperatorConfig("replace", {"new_value": _REDACTED}),
            "PEM_KEY": OperatorConfig("replace", {"new_value": _REDACTED}),
            "BEARER_TOKEN": OperatorConfig("replace", {"new_value": _REDACTED}),
            "CONNECTION_STRING": OperatorConfig("replace", {"new_value": _REDACTED}),
            "AWS_KEY": OperatorConfig("replace", {"new_value": _REDACTED}),
            "GITHUB_TOKEN": OperatorConfig("replace", {"new_value": _REDACTED}),
        },
    )
    return anonymized.text, len(results)


# =============================================================================
# Public API
# =============================================================================


def scrub_text(text: str) -> tuple[str, ScrubStats]:
    """Scrub secrets and PII from text. Returns (scrubbed_text, stats)."""
    try:
        if SCRUB_ENGINE == "presidio":
            text, total = _presidio_scrub(text)
        else:
            text, total = _legacy_scrub(text)
        if total:
            _log.info("Scrubbed %d sensitive item(s) [engine=%s]", total, SCRUB_ENGINE)
        return text, ScrubStats(redactions=total)
    except Exception as exc:
        _log.warning("Scrubbing failed (uploading as-is): %s", exc)
        return text, ScrubStats()
