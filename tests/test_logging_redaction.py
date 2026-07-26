"""Secret redaction tests (spec §10)."""

from __future__ import annotations

from jarvis.kernel.logging import REDACTED, redact


def test_secret_keys_are_redacted() -> None:
    payload = {"api_key": "abc123", "business_id": "biz_1"}
    assert redact(payload) == {"api_key": REDACTED, "business_id": "biz_1"}


def test_nested_structures_are_redacted() -> None:
    payload = {"scope": {"credentials": {"token": "t"}, "tools": ["web_search"]}}
    result = redact(payload)
    assert result["scope"]["credentials"] == REDACTED
    assert result["scope"]["tools"] == ["web_search"]


def test_bearer_tokens_in_free_text_are_redacted() -> None:
    assert REDACTED in redact("Authorization: Bearer sk-abcdefghijklmnopqrstuvwxyz")


def test_database_urls_with_passwords_are_redacted() -> None:
    assert REDACTED in redact("postgresql+asyncpg://jarvis:hunter2@db:5432/jarvis")


def test_ordinary_values_pass_through() -> None:
    assert redact("published today's post") == "published today's post"
