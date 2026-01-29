"""Custom exceptions for SDLC Agent System."""


class SDLCAgentError(Exception):
    """Base exception for all SDLC Agent errors."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | Details: {self.details}"
        return self.message


class ConfigurationError(SDLCAgentError):
    """Raised when configuration is invalid or missing."""

    pass


class GitHubAPIError(SDLCAgentError):
    """Raised when GitHub API operations fail."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, details)
        self.status_code = status_code


class LLMError(SDLCAgentError):
    """Raised when LLM operations fail."""

    def __init__(
        self,
        message: str,
        provider: str | None = None,
        model: str | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, details)
        self.provider = provider
        self.model = model


class CodeGenerationError(SDLCAgentError):
    """Raised when code generation fails."""

    def __init__(
        self,
        message: str,
        file_path: str | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, details)
        self.file_path = file_path


class ReviewError(SDLCAgentError):
    """Raised when code review operations fail."""

    def __init__(
        self,
        message: str,
        pr_number: int | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, details)
        self.pr_number = pr_number


class MaxIterationsError(SDLCAgentError):
    """Raised when maximum iterations limit is reached."""

    def __init__(
        self,
        message: str,
        current_iteration: int,
        max_iterations: int,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, details)
        self.current_iteration = current_iteration
        self.max_iterations = max_iterations


class ValidationError(SDLCAgentError):
    """Raised when validation fails."""

    pass


class GitOperationError(SDLCAgentError):
    """Raised when git operations fail."""

    pass
