from __future__ import annotations

from datetime import datetime
from typing import Any

from nakama_kun.ai.models.message import Message
from nakama_kun.memory.interfaces import MemoryRepository


class NoOpMemoryRepository(MemoryRepository):
    """Fallback repository that performs no persistence.

    Used when `memory_enabled` is set to False in configuration.
    """

    def create_conversation(self, title: str, mode: str) -> str:
        return ""

    def get_conversations(self, limit: int = 20) -> list[dict[str, Any]]:
        return []

    def get_latest_conversation(self, mode: str) -> dict[str, Any] | None:
        return None

    def add_message(self, conversation_id: str, message: Message) -> None:
        pass

    def get_messages(self, conversation_id: str) -> list[Message]:
        return []

    def clear_conversation(self, conversation_id: str) -> None:
        pass

    def clear_all_conversations(self) -> None:
        pass

    def save_project_summary(self, project_name: str, summary: str) -> None:
        pass

    def get_project_summary(self, project_name: str) -> str | None:
        return None

    def save_preference(self, key: str, value: str) -> None:
        pass

    def get_preference(self, key: str, default: str | None = None) -> str | None:
        return default

    def delete_preference(self, key: str) -> None:
        pass

    def get_all_preferences(self) -> dict[str, str]:
        return {}

    def save_task_metadata(
        self,
        task_id: str,
        description: str,
        status: str,
        finished_at: datetime | None = None,
    ) -> None:
        pass

    def get_task_metadata(self, task_id: str) -> dict[str, Any] | None:
        return None

    def list_tasks(self, limit: int = 20) -> list[dict[str, Any]]:
        return []

    def clear_all(self) -> None:
        pass
