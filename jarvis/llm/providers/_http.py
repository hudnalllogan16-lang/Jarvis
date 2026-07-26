"""Shared HTTP plumbing for provider transports."""

from __future__ import annotations

from typing import Any

import httpx

from jarvis.kernel.errors import ProviderError
from jarvis.kernel.logging import get_logger

logger = get_logger(__name__)


async def post_json(
    client: httpx.AsyncClient,
    url: str,
    payload: dict[str, Any],
    *,
    provider: str,
) -> dict[str, Any]:
    """POST JSON and return the decoded body, normalising failures.

    Args:
        client: Shared async client.
        url: Absolute endpoint URL.
        payload: Request body.
        provider: Provider name, for error context.

    Returns:
        The decoded JSON body.

    Raises:
        ProviderError: On transport failure, non-2xx status, or invalid JSON.
            Response bodies are not logged: they can echo prompt content and, on
            some providers, the submitted headers (spec §10).
    """
    try:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        body: dict[str, Any] = response.json()
    except httpx.HTTPStatusError as exc:
        raise ProviderError(f"{provider} returned HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise ProviderError(f"{provider} transport failure: {type(exc).__name__}") from exc
    except ValueError as exc:
        raise ProviderError(f"{provider} returned a non-JSON body") from exc
    return body
