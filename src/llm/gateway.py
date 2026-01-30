"""LLM Gateway - unified interface for different LLM providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.config import LLMProvider, Settings
from src.core.exceptions import LLMError

logger = structlog.get_logger()

# Langfuse integration - initialized lazily
_langfuse_client = None
_langfuse_enabled = False


def _init_langfuse(settings: Settings) -> bool:
    """Initialize Langfuse if configured. Returns True if enabled."""
    global _langfuse_client, _langfuse_enabled

    if not settings.langfuse_enabled:
        logger.info(
            "langfuse_disabled",
            reason="LANGFUSE_PUBLIC_KEY and/or LANGFUSE_SECRET_KEY not set",
        )
        return False

    try:
        from langfuse import Langfuse

        _langfuse_client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_base_url,
        )

        # Verify connection
        if _langfuse_client.auth_check():
            _langfuse_enabled = True
            logger.info(
                "langfuse_enabled",
                host=settings.langfuse_base_url or "default",
            )
            return True
        else:
            logger.warning("langfuse_auth_failed", reason="Auth check failed")
            return False

    except Exception as e:
        logger.warning("langfuse_init_failed", error=str(e))
        return False


def _get_openai_client(settings: Settings) -> Any:
    """Get OpenAI client - instrumented with Langfuse if enabled."""
    if _langfuse_enabled:
        from langfuse.openai import OpenAI
    else:
        from openai import OpenAI

    return OpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=settings.openai_timeout,
    )


def flush_langfuse() -> None:
    """Flush Langfuse queue. Call this before process exit."""
    if _langfuse_client is not None:
        try:
            _langfuse_client.flush()
        except Exception as e:
            logger.warning("langfuse_flush_failed", error=str(e))


@dataclass
class LLMResponse:
    """Response from LLM."""

    content: str
    model: str
    provider: str
    usage: dict[str, int]
    raw_response: Any = None

    @property
    def total_tokens(self) -> int:
        """Get total tokens used."""
        return self.usage.get("total_tokens", 0)


class BaseLLMProvider(ABC):
    """Base class for LLM providers."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Generate a response from the LLM."""
        pass

    @abstractmethod
    def generate_with_context(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Generate a response with full message context."""
        pass


class OpenAIProvider(BaseLLMProvider):
    """OpenAI GPT provider (also supports OpenAI-compatible APIs)."""

    def __init__(
        self,
        client: Any,
        model: str = "gpt-4o-mini",
        base_url: str | None = None,
    ) -> None:
        """
        Initialize OpenAI provider.

        Args:
            client: Pre-configured OpenAI client (may be Langfuse-instrumented)
            model: Model name to use
            base_url: Base URL for logging purposes
        """
        self._client = client
        self._model = model
        self._base_url = base_url
        self._log = logger.bind(
            component="openai_provider",
            model=model,
            base_url=base_url or "default",
            langfuse_enabled=_langfuse_enabled,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        reraise=True,
    )
    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Generate a response from OpenAI."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        return self.generate_with_context(messages, temperature, max_tokens)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        reraise=True,
    )
    def generate_with_context(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Generate a response with full message context."""
        try:
            self._log.debug(
                "openai_request",
                messages_count=len(messages),
                temperature=temperature,
            )

            response = self._client.chat.completions.create(
                model=self._model,
                messages=messages,  # type: ignore
                temperature=temperature,
                max_tokens=max_tokens,
            )

            content = response.choices[0].message.content or ""
            usage = {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            }

            self._log.debug("openai_response", tokens=usage["total_tokens"])

            return LLMResponse(
                content=content,
                model=self._model,
                provider="openai",
                usage=usage,
                raw_response=response,
            )

        except Exception as e:
            self._log.error("openai_error", error=str(e))
            raise LLMError(
                f"OpenAI API error: {e}",
                provider="openai",
                model=self._model,
                details={"error": str(e)},
            ) from e


class YandexGPTProvider(BaseLLMProvider):
    """YandexGPT provider."""

    API_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

    def __init__(
        self,
        api_key: str,
        folder_id: str,
        model: str = "yandexgpt-lite",
    ) -> None:
        self._api_key = api_key
        self._folder_id = folder_id
        self._model = model
        self._log = logger.bind(component="yandex_provider", model=model)

    def _get_model_uri(self) -> str:
        """Get full model URI for Yandex API."""
        return f"gpt://{self._folder_id}/{self._model}"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        reraise=True,
    )
    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Generate a response from YandexGPT."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "text": system_prompt})
        messages.append({"role": "user", "text": prompt})

        return self.generate_with_context(messages, temperature, max_tokens)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        reraise=True,
    )
    def generate_with_context(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Generate a response with full message context."""
        try:
            # Convert message format if needed (OpenAI style -> Yandex style)
            yandex_messages = []
            for msg in messages:
                yandex_messages.append({
                    "role": msg.get("role", "user"),
                    "text": msg.get("content") or msg.get("text", ""),
                })

            payload = {
                "modelUri": self._get_model_uri(),
                "completionOptions": {
                    "stream": False,
                    "temperature": temperature,
                    "maxTokens": str(max_tokens),
                },
                "messages": yandex_messages,
            }

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Api-Key {self._api_key}",
            }

            self._log.debug(
                "yandex_request",
                messages_count=len(messages),
                temperature=temperature,
            )

            with httpx.Client(timeout=120.0) as client:
                response = client.post(
                    self.API_URL,
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()

            result = data.get("result", {})
            alternatives = result.get("alternatives", [])
            content = alternatives[0]["message"]["text"] if alternatives else ""

            usage_data = result.get("usage", {})
            usage = {
                "prompt_tokens": int(usage_data.get("inputTextTokens", 0)),
                "completion_tokens": int(usage_data.get("completionTokens", 0)),
                "total_tokens": int(usage_data.get("totalTokens", 0)),
            }

            self._log.debug("yandex_response", tokens=usage["total_tokens"])

            return LLMResponse(
                content=content,
                model=self._model,
                provider="yandex",
                usage=usage,
                raw_response=data,
            )

        except httpx.HTTPStatusError as e:
            self._log.error("yandex_http_error", status=e.response.status_code)
            raise LLMError(
                f"YandexGPT API error: {e.response.status_code}",
                provider="yandex",
                model=self._model,
                details={"status_code": e.response.status_code, "error": str(e)},
            ) from e
        except Exception as e:
            self._log.error("yandex_error", error=str(e))
            raise LLMError(
                f"YandexGPT error: {e}",
                provider="yandex",
                model=self._model,
                details={"error": str(e)},
            ) from e


class LLMGateway:
    """
    Unified gateway for LLM operations.

    Supports multiple providers and handles failover.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._provider: BaseLLMProvider | None = None
        self._log = logger.bind(component="llm_gateway")
        self._init_provider()

    def _init_provider(self) -> None:
        """Initialize the configured LLM provider."""
        # Initialize Langfuse first (if configured)
        _init_langfuse(self._settings)

        if self._settings.llm_provider == LLMProvider.OPENAI:
            if not self._settings.openai_api_key:
                raise LLMError("OpenAI API key not configured", provider="openai")

            # Get OpenAI client (instrumented with Langfuse if enabled)
            client = _get_openai_client(self._settings)

            self._provider = OpenAIProvider(
                client=client,
                model=self._settings.openai_model,
                base_url=self._settings.openai_base_url,
            )
            self._log.info(
                "provider_initialized",
                provider="openai",
                model=self._settings.openai_model,
                base_url=self._settings.openai_base_url or "default",
                langfuse_enabled=_langfuse_enabled,
            )

        elif self._settings.llm_provider == LLMProvider.YANDEX:
            if not self._settings.yandex_api_key or not self._settings.yandex_folder_id:
                raise LLMError("YandexGPT credentials not configured", provider="yandex")
            self._provider = YandexGPTProvider(
                api_key=self._settings.yandex_api_key,
                folder_id=self._settings.yandex_folder_id,
                model=self._settings.yandex_model,
            )
            self._log.info(
                "provider_initialized",
                provider="yandex",
                model=self._settings.yandex_model,
            )

    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """
        Generate a response from the configured LLM.

        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            temperature: Generation temperature
            max_tokens: Maximum tokens to generate

        Returns:
            LLMResponse with generated content
        """
        if not self._provider:
            raise LLMError("No LLM provider configured")

        return self._provider.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def generate_with_context(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """
        Generate a response with full conversation context.

        Args:
            messages: List of messages with role and content
            temperature: Generation temperature
            max_tokens: Maximum tokens to generate

        Returns:
            LLMResponse with generated content
        """
        if not self._provider:
            raise LLMError("No LLM provider configured")

        return self._provider.generate_with_context(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def generate_code(
        self,
        prompt: str,
        context: str = "",
        language: str = "python",
    ) -> str:
        """
        Generate code with specialized prompting.

        Args:
            prompt: Description of what code to generate
            context: Additional context (existing code, file structure, etc.)
            language: Target programming language

        Returns:
            Generated code as string
        """
        system_prompt = f"""You are an expert {language} developer.
Generate clean, well-documented, production-ready code.
Follow best practices and include appropriate error handling.
Only output the code, no explanations unless asked."""

        full_prompt = prompt
        if context:
            full_prompt = f"Context:\n{context}\n\nTask:\n{prompt}"

        response = self.generate(
            prompt=full_prompt,
            system_prompt=system_prompt,
            temperature=0.3,  # Lower temperature for more deterministic code
        )

        return self._extract_code(response.content)

    def _extract_code(self, content: str) -> str:
        """Extract code from markdown code blocks if present."""
        import re

        # Try to extract code from markdown code blocks
        code_block_pattern = r"```(?:\w+)?\n(.*?)```"
        matches = re.findall(code_block_pattern, content, re.DOTALL)

        if matches:
            return "\n\n".join(matches)

        # Return as-is if no code blocks found
        return content.strip()
