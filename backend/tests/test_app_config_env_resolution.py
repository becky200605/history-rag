"""Tests for AppConfig environment-variable resolution."""

from src.config.app_config import AppConfig


def test_resolve_env_variables_supports_default_value(monkeypatch):
    monkeypatch.delenv("QDRANT_MODE", raising=False)

    resolved = AppConfig.resolve_env_variables("${QDRANT_MODE:-local}")

    assert resolved == "local"


def test_resolve_env_variables_prefers_env_over_default(monkeypatch):
    monkeypatch.setenv("QDRANT_MODE", "server")

    resolved = AppConfig.resolve_env_variables("${QDRANT_MODE:-local}")

    assert resolved == "server"


def test_resolve_env_variables_supports_empty_default(monkeypatch):
    monkeypatch.delenv("QDRANT_URL", raising=False)

    resolved = AppConfig.resolve_env_variables("${QDRANT_URL:-}")

    assert resolved == ""


def test_resolve_env_variables_keeps_legacy_dollar_syntax(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    resolved = AppConfig.resolve_env_variables("$OPENAI_API_KEY")

    assert resolved == "test-key"
