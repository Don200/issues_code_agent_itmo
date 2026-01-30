"""Tests for configuration."""

import os
from unittest.mock import patch

import pytest

from src.core.config import Settings


def test_settings_from_env() -> None:
    """Test loading settings from environment variables."""
    env = {
        "GITHUB_TOKEN": "test-token",
        "GITHUB_REPOSITORY": "owner/repo",
        "OPENAI_API_KEY": "sk-test",
    }

    with patch.dict(os.environ, env, clear=True):
        settings = Settings()

        assert settings.github_token == "test-token"
        assert settings.github_repository == "owner/repo"
        assert settings.openai_api_key == "sk-test"


def test_repository_owner_and_name() -> None:
    """Test repository owner and name extraction."""
    env = {
        "GITHUB_TOKEN": "test-token",
        "GITHUB_REPOSITORY": "myorg/myrepo",
        "OPENAI_API_KEY": "sk-test",
    }

    with patch.dict(os.environ, env, clear=True):
        settings = Settings()

        assert settings.repo_owner == "myorg"
        assert settings.repo_name == "myrepo"


def test_invalid_repository_format() -> None:
    """Test validation of repository format."""
    env = {
        "GITHUB_TOKEN": "test-token",
        "GITHUB_REPOSITORY": "invalid-format",
        "OPENAI_API_KEY": "sk-test",
    }

    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValueError, match="owner/repo"):
            Settings()


def test_default_values() -> None:
    """Test default configuration values."""
    env = {
        "GITHUB_TOKEN": "test-token",
        "GITHUB_REPOSITORY": "owner/repo",
        "OPENAI_API_KEY": "sk-test",
    }

    with patch.dict(os.environ, env, clear=True):
        settings = Settings()

        assert settings.max_iterations == 5
        assert settings.openai_model == "gpt-4o-mini"
        assert settings.log_level == "INFO"


def test_langfuse_enabled() -> None:
    """Test Langfuse enabled detection."""
    env = {
        "GITHUB_TOKEN": "test-token",
        "GITHUB_REPOSITORY": "owner/repo",
        "OPENAI_API_KEY": "sk-test",
        "LANGFUSE_PUBLIC_KEY": "pk-lf-test",
        "LANGFUSE_SECRET_KEY": "sk-lf-test",
    }

    with patch.dict(os.environ, env, clear=True):
        settings = Settings()
        assert settings.langfuse_enabled is True


def test_langfuse_disabled_without_keys() -> None:
    """Test Langfuse disabled when keys not set."""
    env = {
        "GITHUB_TOKEN": "test-token",
        "GITHUB_REPOSITORY": "owner/repo",
        "OPENAI_API_KEY": "sk-test",
    }

    with patch.dict(os.environ, env, clear=True):
        settings = Settings()
        assert settings.langfuse_enabled is False
