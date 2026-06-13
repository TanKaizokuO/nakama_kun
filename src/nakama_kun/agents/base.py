from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from nakama_kun.ai.services.chat_service import ChatService


class BaseAgent(ABC):
    """Abstract base class for specialized agents in Nakama-kun."""

    def __init__(self, chat_service: ChatService) -> None:
        self.chat_service = chat_service

    @abstractmethod
    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute the agent's logic and return a dictionary of state updates."""
        pass
