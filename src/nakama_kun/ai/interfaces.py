from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from nakama_kun.ai.config import AISettings
from nakama_kun.ai.models.message import Message
from nakama_kun.ai.models.response import AIResponse


class LLMProvider(ABC):
    """Abstract interface that all nakama_kun LLM providers must implement."""

    settings: AISettings

    @abstractmethod
    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
    ) -> AIResponse:
        """
        Generate a complete response for a list of messages.

        Args:
            messages: List of conversation history messages.
            tools: Optional list of tools/functions available to the model.
            tool_choice: Optional tool choice specification.

        Returns:
            An AIResponse instance containing content, usage, and latency.
        """
        pass

    @abstractmethod
    def generate_stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
    ) -> AsyncIterator[str]:
        """
        Stream response tokens for a list of messages.

        Args:
            messages: List of conversation history messages.
            tools: Optional list of tools/functions available to the model.
            tool_choice: Optional tool choice specification.

        Yields:
            Token strings progressively.
        """
        pass

    @abstractmethod
    async def verify_connectivity(self) -> bool:
        """
        Verify connection to the provider.

        Returns:
            True if connection is successful.

        Raises:
            AIError: If verification fails due to missing keys, rate limits, or network errors.
        """
        pass
