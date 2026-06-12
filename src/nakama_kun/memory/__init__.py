from __future__ import annotations

from nakama_kun.config.memory import MemorySettings
from nakama_kun.memory.interfaces import MemoryRepository
from nakama_kun.memory.noop import NoOpMemoryRepository
from nakama_kun.memory.sqlite import SQLiteMemoryRepository


def get_memory_repository() -> MemoryRepository:
    """Instantiate and return the configured memory repository backend.

    If memory is disabled via configuration, returns a NoOpMemoryRepository.
    """
    settings = MemorySettings()
    if not settings.memory_enabled:
        return NoOpMemoryRepository()

    return SQLiteMemoryRepository(settings.memory_db_path)


__all__ = [
    "MemoryRepository",
    "SQLiteMemoryRepository",
    "NoOpMemoryRepository",
    "get_memory_repository",
]
