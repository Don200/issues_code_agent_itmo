"""Tests for configuration."""

import os
from unittest.mock import patch

import pytest

from src.core.config import LLMProvider, Settings


def test_settings_from_env() -> None:
    """Test loading settings from environment variables."""
    env = {
        "GITHUB_TOKEN": "test-token",
        "GITHUB_REPOSITORY": "owner/repo",
        "OPENAI_API_KEY": "sk-test",
        "LLM_PROVIDER": "openai",
    }

    with patch.dict(os.environ, env, clear=True):
        settings = Settings()

        assert settings.github_token == "test-token"
        assert settings.github_repository == "owner/repo"
        assert settings.openai_api_key == "sk-test"
        assert settings.llm_provider == LLMProvider.OPENAI


def test_repository_owner_and_name() -> None:
    """Test repository owner and name extraction."""
    env = {
        "GITHUB_TOKEN": "test-token",
        "GITHUB_REPOSITORY": "myorg/myrepo",
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
    }

    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValueError, match="owner/repo"):
            Settings()


def test_llm_provider_normalization() -> None:
    """Test LLM provider value normalization."""
    env = {
        "GITHUB_TOKEN": "test-token",
        "GITHUB_REPOSITORY": "owner/repo",
        "LLM_PROVIDER": "OPENAI",  # uppercase
    }

    with patch.dict(os.environ, env, clear=True):
        settings = Settings()
        assert settings.llm_provider == LLMProvider.OPENAI


def test_default_values() -> None:
    """Test default configuration values."""
    env = {
        "GITHUB_TOKEN": "test-token",
        "GITHUB_REPOSITORY": "owner/repo",
    }

    with patch.dict(os.environ, env, clear=True):
        settings = Settings()

        assert settings.max_iterations == 5
        assert settings.openai_model == "gpt-4o-mini"
        assert settings.log_level == "INFO"


def test_validate_openai_config() -> None:
    """Test OpenAI configuration validation."""
    env = {
        "GITHUB_TOKEN": "test-token",
        "GITHUB_REPOSITORY": "owner/repo",
        "LLM_PROVIDER": "openai",
        # Missing OPENAI_API_KEY
    }

    with patch.dict(os.environ, env, clear=True):
        settings = Settings()
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            settings.validate_llm_config()


def test_validate_yandex_config() -> None:
    """Test YandexGPT configuration validation."""
    env = {
        "GITHUB_TOKEN": "test-token",
        "GITHUB_REPOSITORY": "owner/repo",
        "LLM_PROVIDER": "yandex",
        "YANDEX_API_KEY": "test-key",
        # Missing YANDEX_FOLDER_ID
    }

    with patch.dict(os.environ, env, clear=True):
        settings = Settings()
        with pytest.raises(ValueError, match="YANDEX_FOLDER_ID"):
            settings.validate_llm_config()
