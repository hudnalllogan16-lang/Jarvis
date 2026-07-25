"""Kimi (Moonshot AI) LLM provider implementation.

Requires the ``openai`` package (Kimi uses an OpenAI-compatible API).
"""

from __future__ import annotations

from typing import Any

from kernel.config.settings import SecretStr
from services.llm.models import LLMRequest, LLMResponse


def _unwrap_secret(value: SecretStr | str | None) -> str | None:
    """Extract the string value from a SecretStr if needed."""
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return value


class KimiProvider:
    """Production provider for Kimi (Moonshot AI) models.

    Uses the OpenAI-compatible HTTP API. The ``api_key`` and ``base_url``
    are typically sourced from ``JarvisSettings``.
    """

    def __init__(
        self,
        api_key: SecretStr | str | None = None,
        base_url: str | None = None,
        model: str = "kimi-latest",
    ) -> None:
        """Initialize the Kimi provider.

        Args:
            api_key: Kimi API key.
            base_url: Optional custom base URL.
            model: Model identifier to use.

        """
        self._api_key = _unwrap_secret(api_key)
        self._base_url = base_url or "https://api.moonshot.cn/v1"
        self._model = model
        self._client: Any | None = None

    def _get_client(self) -> Any:
        """Lazy-load the OpenAI client."""
        if self._client is None:
            try:
                import openai
            except ImportError as exc:
                raise ImportError(
                    "The 'openai' package is required for KimiProvider. "
                    "Install it with: pip install openai"
                ) from exc
            self._client = openai.OpenAI(  # type: ignore[reportUnknownMemberType]
                api_key=self._api_key,
                base_url=self._base_url,
            )
        return self._client  # type: ignore[reportUnknownVariableType]

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Send the request to Kimi and return the response.

        Args:
            request: The structured request.

        Returns:
            The model's response.

        """
        client = self._get_client()

        messages = [
            {"role": m.role.value, "content": m.content}
            for m in request.messages
        ]

        params: dict[str, Any] = {
            "model": request.model or self._model,
            "messages": messages,
            "temperature": request.temperature,
        }
        if request.max_tokens is not None:
            params["max_tokens"] = request.max_tokens
        params.update(request.extra)

        completion = client.chat.completions.create(**params)

        return LLMResponse(
            content=completion.choices[0].message.content or "",
            model=completion.model,
            usage=completion.usage.model_dump() if completion.usage else None,
            raw=completion,
        )
