"""Tests for the mock LLM provider."""

from services.llm.models import LLMRequest, Message, MessageRole
from services.llm.providers.mock_provider import MockProvider


def test_mock_provider_returns_response() -> None:
    """Mock provider should return a response for any request."""
    provider = MockProvider()
    request = LLMRequest(
        messages=[Message(role=MessageRole.USER, content="Hello")]
    )
    response = provider.complete(request)
    assert response.content
    assert response.model == "mock"


def test_mock_provider_remembers() -> None:
    """Mock provider should acknowledge remember commands."""
    provider = MockProvider()
    request = LLMRequest(
        messages=[Message(role=MessageRole.USER, content="Remember that I like tea")]
    )
    response = provider.complete(request)
    assert response.content == "Stored."
