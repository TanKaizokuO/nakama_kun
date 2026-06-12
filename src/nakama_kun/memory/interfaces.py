from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from nakama_kun.ai.models.message import Message


class MemoryRepository(ABC):
    """Abstract interface defining required memory operations for nakama_kun.

    Allows plugging in alternate backends (e.g. SQLite, JSON, or Vector stores).
    """

    # ------------------------------------------------------------------
    # Conversations & Messages
    # ------------------------------------------------------------------

    @abstractmethod
    def create_conversation(self, title: str, mode: str) -> str:
        """Create a new conversation tracking record and return its unique ID."""
        pass

    @abstractmethod
    def get_conversations(self, limit: int = 20) -> list[dict[str, Any]]:
        """Retrieve recent conversations ordered by creation date."""
        pass

    @abstractmethod
    def get_latest_conversation(self, mode: str) -> dict[str, Any] | None:
        """Retrieve the most recently active conversation for a given mode."""
        pass

    @abstractmethod
    def add_message(self, conversation_id: str, message: Message) -> None:
        """Add a Message model object to a specific conversation history."""
        pass

    @abstractmethod
    def get_messages(self, conversation_id: str) -> list[Message]:
        """Retrieve all messages for a specific conversation in chronological order."""
        pass

    @abstractmethod
    def clear_conversation(self, conversation_id: str) -> None:
        """Delete a conversation and all of its associated messages."""
        pass

    @abstractmethod
    def clear_all_conversations(self) -> None:
        """Delete all conversation records and messages."""
        pass

    # ------------------------------------------------------------------
    # Project Context Summaries
    # ------------------------------------------------------------------

    @abstractmethod
    def save_project_summary(self, project_name: str, summary: str) -> None:
        """Save/overwrite the workspace analysis summary for a specific project."""
        pass

    @abstractmethod
    def get_project_summary(self, project_name: str) -> str | None:
        """Retrieve the latest cached summary for a specific project."""
        pass

    # ------------------------------------------------------------------
    # User Preferences
    # ------------------------------------------------------------------

    @abstractmethod
    def save_preference(self, key: str, value: str) -> None:
        """Save or overwrite a user preference key-value pair."""
        pass

    @abstractmethod
    def get_preference(self, key: str, default: str | None = None) -> str | None:
        """Retrieve a user preference or return default value."""
        pass

    @abstractmethod
    def delete_preference(self, key: str) -> None:
        """Delete a specific user preference by key."""
        pass

    @abstractmethod
    def get_all_preferences(self) -> dict[str, str]:
        """Retrieve all stored user preferences."""
        pass

    # ------------------------------------------------------------------
    # Agent Tasks Metadata
    # ------------------------------------------------------------------

    @abstractmethod
    def save_task_metadata(
        self,
        task_id: str,
        description: str,
        status: str,
        finished_at: datetime | None = None,
    ) -> None:
        """Record or update execution metadata for an autonomous agent task."""
        pass

    @abstractmethod
    def get_task_metadata(self, task_id: str) -> dict[str, Any] | None:
        """Retrieve execution metadata details for a specific task ID."""
        pass

    @abstractmethod
    def list_tasks(self, limit: int = 20) -> list[dict[str, Any]]:
        """List recent tasks and their execution status."""
        pass

    # ------------------------------------------------------------------
    # Global Wipes
    # ------------------------------------------------------------------

    @abstractmethod
    def clear_all(self) -> None:
        """Perform a complete wipe of all tables/records from memory."""
        pass
