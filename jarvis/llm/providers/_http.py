"""Shared HTTP plumbing for provider transports."""

from __future__ import annotations

from typing import Any

import httpx

from jarvis.kernel.errors import ProviderError
from jarvis.kernel.logging import get_logger

logger = get_logger(__name__)


async def get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    provider: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """GET JSON and return the decoded body, normalising failures.

    The read half of `post_json` below, added for the model catalogs the
    startup check reads (`jarvis/llm/validation.py`). Same normalisation and
    the same silence about bodies: a catalog response is not prompt content,
    but a 401 body can echo the submitted key material, and one function that
    sometimes logs bodies is how that leaks (spec §10).

    Args:
        client: Shared async client.
        url: Endpoint path or URL.
        provider: Provider name, for error context.
        params: Optional query parameters.

    Returns:
        The decoded JSON body.

    Raises:
        ProviderError: On transport failure, non-2xx status, or invalid JSON.
    """
    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
        body: dict[str, Any] = response.json()
    except httpx.HTTPStatusError as exc:
        raise ProviderError(f"{provider} returned HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise ProviderError(f"{provider} transport failure: {type(exc).__name__}") from exc
    except ValueError as exc:
        raise ProviderError(f"{provider} returned a non-JSON body") from exc
    return body


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
