"""Configuration management for SDLC Agent System."""

from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    """Supported LLM providers."""

    OPENAI = "openai"
    YANDEX = "yandex"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # GitHub Configuration
    github_token: str = Field(..., description="GitHub API token")
    github_repository: str = Field(..., description="Repository in format owner/repo")

    # LLM Configuration
    llm_provider: LLMProvider = Field(
        default=LLMProvider.OPENAI,
        description="LLM provider to use",
    )

    # OpenAI Configuration
    openai_api_key: str | None = Field(default=None, description="OpenAI API key")
    openai_base_url: str | None = Field(
        default=None,
        description="Custom base URL for OpenAI-compatible API (e.g., Azure, Ollama, vLLM)",
    )
    openai_model: str = Field(default="gpt-4o-mini", description="OpenAI model to use")
    openai_max_tokens: int = Field(default=4096, description="Max tokens for OpenAI")
    openai_timeout: int = Field(default=120, description="Request timeout in seconds")

    # YandexGPT Configuration
    yandex_api_key: str | None = Field(default=None, description="YandexGPT API key")
    yandex_folder_id: str | None = Field(default=None, description="Yandex Cloud folder ID")
    yandex_model: str = Field(default="yandexgpt-lite", description="YandexGPT model")

    # Agent Configuration
    max_iterations: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum iterations for fix cycle",
    )
    iteration_cooldown: int = Field(
        default=30,
        description="Cooldown between iterations in seconds",
    )

    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(default="json", description="Log format (json or text)")

    # Paths
    workspace_dir: Path = Field(
        default=Path("./workspace"),
        description="Working directory for code operations",
    )

    @field_validator("github_repository")
    @classmethod
    def validate_repository_format(cls, v: str) -> str:
        """Validate repository format is owner/repo."""
        if "/" not in v or v.count("/") != 1:
            raise ValueError("Repository must be in format 'owner/repo'")
        owner, repo = v.split("/")
        if not owner or not repo:
            raise ValueError("Both owner and repo must be non-empty")
        return v

    @field_validator("llm_provider", mode="before")
    @classmethod
    def normalize_provider(cls, v: str | LLMProvider) -> LLMProvider:
        """Normalize LLM provider value."""
        if isinstance(v, str):
            return LLMProvider(v.lower())
        return v

    @property
    def repo_owner(self) -> str:
        """Get repository owner."""
        return self.github_repository.split("/")[0]

    @property
    def repo_name(self) -> str:
        """Get repository name."""
        return self.github_repository.split("/")[1]

    def validate_llm_config(self) -> None:
        """Validate LLM configuration based on selected provider."""
        if self.llm_provider == LLMProvider.OPENAI:
            if not self.openai_api_key:
                raise ValueError("OPENAI_API_KEY is required when using OpenAI provider")
        elif self.llm_provider == LLMProvider.YANDEX:
            if not self.yandex_api_key:
                raise ValueError("YANDEX_API_KEY is required when using Yandex provider")
            if not self.yandex_folder_id:
                raise ValueError("YANDEX_FOLDER_ID is required when using Yandex provider")


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
