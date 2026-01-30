"""LLM Gateway - unified interface for OpenAI and compatible APIs."""

from dataclasses import dataclass
from typing import Any

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.config import Settings
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
    usage: dict[str, int]
    raw_response: Any = None

    @property
    def total_tokens(self) -> int:
        """Get total tokens used."""
        return self.usage.get("total_tokens", 0)


class LLMGateway:
    """
    Gateway for OpenAI and compatible LLM APIs.

    Supports custom base URLs for Azure, Ollama, vLLM, etc.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._log = logger.bind(component="llm_gateway")

        # Initialize Langfuse first (if configured)
        _init_langfuse(settings)

        # Get OpenAI client (instrumented with Langfuse if enabled)
        self._client = _get_openai_client(settings)
        self._model = settings.openai_model

        self._log.info(
            "gateway_initialized",
            model=self._model,
            base_url=settings.openai_base_url or "default",
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
        """Generate a response from the LLM."""
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
                "llm_request",
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

            self._log.debug("llm_response", tokens=usage["total_tokens"])

            return LLMResponse(
                content=content,
                model=self._model,
                usage=usage,
                raw_response=response,
            )

        except Exception as e:
            self._log.error("llm_error", error=str(e))
            raise LLMError(
                f"LLM API error: {e}",
                provider="openai",
                model=self._model,
                details={"error": str(e)},
            ) from e

    def generate_code(
        self,
        prompt: str,
        context: str = "",
        language: str = "python",
    ) -> str:
        """Generate code with specialized prompting."""
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
            temperature=0.3,
        )

        return self._extract_code(response.content)

    def _extract_code(self, content: str) -> str:
        """Extract code from markdown code blocks if present."""
        import re

        code_block_pattern = r"```(?:\w+)?\n(.*?)```"
        matches = re.findall(code_block_pattern, content, re.DOTALL)

        if matches:
            return "\n\n".join(matches)

        return content.strip()
