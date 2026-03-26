"""Tests for the scrub module."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).parent))

from scrub import ScrubStats, scrub_text


def test_scrub_redacts_api_keys():
    text = "OPENAI_API_KEY=sk-test-1234567890\nSECRET_KEY=AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
    scrubbed, stats = scrub_text(text)
    assert "sk-test-" not in scrubbed
    assert "OPENAI_API_KEY=sk-test-1234567890" not in scrubbed
    assert "[secret-redacted]" in scrubbed
    assert stats.redactions >= 1


def test_scrub_redacts_credit_cards():
    text = '{"message": "card 4111111111111111 should not survive"}'
    scrubbed, stats = scrub_text(text)
    assert "4111111111111111" not in scrubbed
    assert stats.redactions >= 1


def test_scrub_preserves_safe_text():
    text = '{"event": "note", "message": "safe marker stays visible"}'
    scrubbed, stats = scrub_text(text)
    assert "safe marker stays visible" in scrubbed
    assert stats.redactions == 0


def test_scrub_stats_addition():
    a = ScrubStats(redactions=3)
    b = ScrubStats(redactions=5)
    c = a + b
    assert c.redactions == 8
