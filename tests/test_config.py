"""Tests for gleaner.config: config file I/O, hook management."""

import json

import pytest

import gleaner.config as config


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path, monkeypatch):
    """Redirect config and settings files to a temp directory."""
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "gleaner.json")
    monkeypatch.setattr(config, "CLAUDE_SETTINGS", tmp_path / ".claude" / "settings.json")


class TestConfigRoundtrip:
    """write_config -> read_config should preserve data."""

    def test_roundtrip(self):
        config.write_config("https://example.com", "gl_abc123")
        cfg = config.read_config()
        assert cfg["url"] == "https://example.com"
        assert cfg["token"] == "gl_abc123"

    def test_read_missing_returns_empty(self):
        assert config.read_config() == {}

    def test_overwrite(self):
        config.write_config("https://old.com", "gl_old")
        config.write_config("https://new.com", "gl_new")
        cfg = config.read_config()
        assert cfg["url"] == "https://new.com"
        assert cfg["token"] == "gl_new"


class TestGetCredentials:
    """get_credentials should prefer env vars over config file."""

    def test_env_vars_take_precedence(self, monkeypatch):
        config.write_config("https://file.com", "gl_file")
        monkeypatch.setenv("GLEANER_URL", "https://env.com")
        monkeypatch.setenv("GLEANER_TOKEN", "gl_env")
        url, token = config.get_credentials()
        assert url == "https://env.com"
        assert token == "gl_env"

    def test_falls_back_to_config(self, monkeypatch):
        config.write_config("https://file.com", "gl_file")
        monkeypatch.delenv("GLEANER_URL", raising=False)
        monkeypatch.delenv("GLEANER_TOKEN", raising=False)
        url, token = config.get_credentials()
        assert url == "https://file.com"
        assert token == "gl_file"

    def test_partial_env_partial_config(self, monkeypatch):
        """URL from env, token from config file."""
        config.write_config("https://file.com", "gl_file")
        monkeypatch.setenv("GLEANER_URL", "https://env.com")
        monkeypatch.delenv("GLEANER_TOKEN", raising=False)
        url, token = config.get_credentials()
        assert url == "https://env.com"
        assert token == "gl_file"

    def test_empty_when_nothing_configured(self, monkeypatch):
        monkeypatch.delenv("GLEANER_URL", raising=False)
        monkeypatch.delenv("GLEANER_TOKEN", raising=False)
        url, token = config.get_credentials()
        assert url == ""
        assert token == ""


class TestHookManagement:
    """install_hook / remove_hook / is_hook_installed manage ~/.claude/settings.json."""

    def test_install_on_empty(self):
        """Installing into a fresh settings.json works."""
        assert config.install_hook() is True
        assert config.is_hook_installed() is True

    def test_install_is_idempotent(self):
        """Second install returns False and doesn't duplicate."""
        config.install_hook()
        assert config.install_hook() is False
        settings = config.read_claude_settings()
        assert len(settings["hooks"]["SessionEnd"]) == 1

    def test_remove(self):
        config.install_hook()
        assert config.remove_hook() is True
        assert config.is_hook_installed() is False

    def test_remove_when_not_installed(self):
        assert config.remove_hook() is False

    def test_preserves_other_hooks(self):
        """Installing/removing gleaner doesn't affect other hooks."""
        other_hook = {"hooks": [{"type": "command", "command": "my-other-hook"}]}
        settings = {"hooks": {"SessionEnd": [other_hook], "PreToolUse": [{"hooks": []}]}}
        config.write_claude_settings(settings)

        config.install_hook()
        s = config.read_claude_settings()
        assert len(s["hooks"]["SessionEnd"]) == 2  # other + gleaner
        assert "PreToolUse" in s["hooks"]

        config.remove_hook()
        s = config.read_claude_settings()
        assert len(s["hooks"]["SessionEnd"]) == 1  # only other remains
        assert s["hooks"]["SessionEnd"][0] == other_hook

    def test_install_remove_roundtrip(self):
        """Install then remove leaves no gleaner trace."""
        config.install_hook()
        config.remove_hook()
        settings = config.read_claude_settings()
        assert settings["hooks"]["SessionEnd"] == []
