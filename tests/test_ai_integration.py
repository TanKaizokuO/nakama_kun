import asyncio
from unittest.mock import AsyncMock, MagicMock

import openai
import pytest

from nakama_kun.ai.config import AISettings
from nakama_kun.ai.exceptions import (
    APIKeyNotFoundError,
    NetworkError,
    RateLimitError,
)
from nakama_kun.ai.models.message import Message
from nakama_kun.ai.providers.openrouter_provider import OpenRouterProvider
from nakama_kun.ai.services.chat_service import ChatService


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear environment variables to ensure hermetic tests."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)


def test_ai_settings_default() -> None:
    settings = AISettings(_env_file=None, openrouter_api_key="secret-key")
    assert settings.openrouter_model == "openai/gpt-5"
    assert settings.model == "openai/gpt-5"


def test_ai_settings_aliases() -> None:
    settings = AISettings(
        _env_file=None, openrouter_api_key="secret-key", openrouter_model="gpt5"
    )
    # The property should map 'gpt5' -> 'openai/gpt-5' via registry
    assert settings.model == "openai/gpt-5"


def test_missing_api_key() -> None:
    settings = AISettings(_env_file=None, openrouter_api_key=None)
    provider = OpenRouterProvider(settings)
    with pytest.raises(APIKeyNotFoundError) as exc_info:
        _ = provider.client
    assert "OpenAI API key not found" in str(exc_info.value)


def test_chat_service_chat_flow() -> None:
    settings = AISettings(_env_file=None, openrouter_api_key="test-key")
    provider = OpenRouterProvider(settings)

    # Mock provider generate
    mock_response = MagicMock()
    mock_response.content = "This is a test response."
    mock_response.model = "openai/gpt-5"
    mock_response.usage.prompt_tokens = 10
    mock_response.usage.completion_tokens = 20
    mock_response.usage.total_tokens = 30
    mock_response.latency = 0.5
    mock_response.choices = [
        MagicMock(
            finish_reason="stop",
            message=MagicMock(
                content="This is a test response.", tool_calls=None
            ),
        )
    ]

    provider.generate = AsyncMock(return_value=mock_response)
    chat_service = ChatService(provider)

    async def run_test() -> None:
        response = await chat_service.chat("Ping")
        assert response.content == "This is a test response."
        assert len(chat_service.history) == 2
        assert chat_service.history[0].role == "user"
        assert chat_service.history[0].content == "Ping"
        assert chat_service.history[1].role == "assistant"
        assert chat_service.history[1].content == "This is a test response."

    asyncio.run(run_test())


def test_provider_exception_mapping() -> None:
    settings = AISettings(_env_file=None, openrouter_api_key="test-key")
    provider = OpenRouterProvider(settings)

    # We mock the internal AsyncOpenAI client
    mock_client = MagicMock()
    mock_completions = MagicMock()

    # Rate limit error mapping
    mock_completions.create = AsyncMock(
        side_effect=openai.RateLimitError(
            message="Rate limit exceeded",
            response=MagicMock(),
            body=None,
        )
    )
    mock_client.chat.completions = mock_completions
    provider._client = mock_client

    async def run_rate_limit() -> None:
        with pytest.raises(RateLimitError):
            await provider.generate([Message(role="user", content="Ping")])

    asyncio.run(run_rate_limit())

    # API connection error mapping
    mock_completions.create = AsyncMock(
        side_effect=openai.APIConnectionError(
            message="Conn error", request=MagicMock()
        )
    )

    async def run_conn_error() -> None:
        with pytest.raises(NetworkError):
            await provider.generate([Message(role="user", content="Ping")])

    asyncio.run(run_conn_error())
