"""Configuration management for SDLC Agent System."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # OpenAI Configuration
    openai_api_key: str = Field(..., description="OpenAI API key")
    openai_base_url: str | None = Field(
        default=None,
        description="Custom base URL for OpenAI-compatible API (e.g., Azure, Ollama, vLLM)",
    )
    openai_model: str = Field(default="gpt-4o-mini", description="OpenAI model to use")
    openai_max_tokens: int = Field(default=4096, description="Max tokens for OpenAI")
    openai_timeout: int = Field(default=120, description="Request timeout in seconds")

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

    # Langfuse Configuration (optional - for LLM observability)
    langfuse_public_key: str | None = Field(default=None, description="Langfuse public key")
    langfuse_secret_key: str | None = Field(default=None, description="Langfuse secret key")
    langfuse_base_url: str | None = Field(
        default=None,
        description="Langfuse base URL (for self-hosted)",
    )

    @property
    def langfuse_enabled(self) -> bool:
        """Check if Langfuse is configured and enabled."""
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

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

    @property
    def repo_owner(self) -> str:
        """Get repository owner."""
        return self.github_repository.split("/")[0]

    @property
    def repo_name(self) -> str:
        """Get repository name."""
        return self.github_repository.split("/")[1]


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
