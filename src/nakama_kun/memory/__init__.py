from __future__ import annotations

from nakama_kun.config.memory import MemorySettings
from nakama_kun.memory.interfaces import MemoryRepository
from nakama_kun.memory.noop import NoOpMemoryRepository
from nakama_kun.memory.sqlite import SQLiteMemoryRepository
from nakama_kun.memory.models import SuccessfulTask, FailureRecord, UserPreference
from nakama_kun.memory.sqlite_store import MemoryStore, SQLiteMemoryStore
from nakama_kun.memory.manager import MemoryManager
from nakama_kun.memory.retriever import ExperienceBundle, ExperienceRetriever
from nakama_kun.memory.indexer import MemoryIndexer


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
    "SuccessfulTask",
    "FailureRecord",
    "UserPreference",
    "MemoryStore",
    "SQLiteMemoryStore",
    "MemoryManager",
    "ExperienceBundle",
    "ExperienceRetriever",
    "MemoryIndexer",
]

