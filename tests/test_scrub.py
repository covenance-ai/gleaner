"""Tests for the scrub module."""

from __future__ import annotations

import json

from gleaner.scrub import ScrubStats, scrub_text


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


# ---------------------------------------------------------------------------
# Integration: realistic JSONL transcripts through the scrubber
# ---------------------------------------------------------------------------

def _make_transcript(messages: list[dict]) -> str:
    """Build a JSONL string from message dicts, same format as Claude Code."""
    return "\n".join(json.dumps(m) for m in messages) + "\n"


def _make_realistic_transcript(pii_content: str) -> str:
    """Wrap PII inside a realistic multi-message Claude Code transcript.

    The PII appears as file content inside a tool_result, which is the most
    common place real secrets appear (Claude reads a file containing them).
    """
    return _make_transcript([
        {
            "type": "user",
            "timestamp": "2026-03-20T10:00:00Z",
            "message": {"content": "Check the config file"},
        },
        {
            "type": "assistant",
            "timestamp": "2026-03-20T10:00:05Z",
            "message": {
                "content": [
                    {"type": "text", "text": "Let me read that."},
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "Read",
                        "input": {"file_path": "/app/config.py"},
                    },
                ]
            },
        },
        {
            "type": "user",
            "timestamp": "2026-03-20T10:00:06Z",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "content": pii_content,
                    }
                ]
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-03-20T10:00:10Z",
            "message": {
                "content": [
                    {"type": "text", "text": "I see the issue. Let me fix it."},
                ]
            },
        },
    ])


class TestScrubRealisticTranscript:
    """Verify the scrubber catches PII embedded in realistic JSONL transcripts.

    These simulate what backfill/upload actually process: full multi-line JSONL
    with PII buried inside tool results (file reads), user messages, etc.
    The scrubber must produce non-zero redactions for each case.
    """

    def test_api_key_in_file_read(self):
        """API key inside a file that Claude read."""
        transcript = _make_realistic_transcript(
            'OPENAI_API_KEY = "sk-proj-abc123def456ghi789jkl012mno345pqr678stu901vwx"'
        )
        scrubbed, stats = scrub_text(transcript)
        assert "sk-proj-abc123def456" not in scrubbed
        assert stats.redactions > 0

    def test_credit_card_in_file_read(self):
        """Credit card number inside a data file that Claude read."""
        transcript = _make_realistic_transcript(
            "customer_name,card_number\nJane Doe,4111111111111111"
        )
        scrubbed, stats = scrub_text(transcript)
        assert "4111111111111111" not in scrubbed
        assert stats.redactions > 0

    def test_email_in_user_message(self):
        """Email address directly in the user's prompt."""
        transcript = _make_transcript([
            {
                "type": "user",
                "timestamp": "2026-03-20T10:00:00Z",
                "message": {"content": "Send results to alice.smith@megacorp.com please"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-03-20T10:00:05Z",
                "message": {"content": [{"type": "text", "text": "Sure."}]},
            },
        ])
        scrubbed, stats = scrub_text(transcript)
        assert "alice.smith@megacorp.com" not in scrubbed
        assert stats.redactions > 0

    def test_multiple_secrets_in_env_file(self):
        """Multiple secrets in a .env file that Claude read."""
        env_content = (
            "DATABASE_URL=postgres://admin:s3cretP4ss@db.internal:5432/prod\n"
            "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n"
            "STRIPE_SECRET_KEY=rk_fake_XXXXXXXXXXXXXXXXXXXXXXXXXXXX\n"
        )
        transcript = _make_realistic_transcript(env_content)
        scrubbed, stats = scrub_text(transcript)
        assert "s3cretP4ss" not in scrubbed
        assert "wJalrXUtnFEMI" not in scrubbed
        assert stats.redactions >= 2

    def test_private_key_in_file_read(self):
        """Full PEM block (header + key body + footer) is redacted."""
        key_content = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn/ygWyF8PbnGy0AHB7MhgHcTz6sE2I2yPB\n"
            "aFDrBz9vFqU4yDBGP2KnNOgMFcMEMwE7OkDZ4KxmLB0qFEaRLhQ5OLzf+DB/XzN\n"
            "-----END RSA PRIVATE KEY-----"
        )
        transcript = _make_realistic_transcript(key_content)
        scrubbed, stats = scrub_text(transcript)
        assert "BEGIN RSA PRIVATE KEY" not in scrubbed
        assert "MIIEpAIBAAKCAQEA" not in scrubbed
        assert "END RSA PRIVATE KEY" not in scrubbed
        assert stats.redactions > 0

    def test_phone_number_not_caught(self):
        """Known gap: piicleaner does not catch US phone numbers in JSONL context."""
        transcript = _make_realistic_transcript(
            "Contact: John Smith\nPhone: (555) 867-5309\nRole: Admin"
        )
        scrubbed, stats = scrub_text(transcript)
        # piicleaner misses this — documenting the gap
        assert "867-5309" in scrubbed
        assert stats.redactions == 0

    def test_safe_transcript_zero_redactions(self):
        """A transcript with no PII should produce zero redactions."""
        transcript = _make_realistic_transcript(
            "def hello():\n    return 'Hello, World!'\n"
        )
        scrubbed, stats = scrub_text(transcript)
        assert "Hello, World!" in scrubbed
        assert stats.redactions == 0
