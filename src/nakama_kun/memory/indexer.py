from __future__ import annotations

import contextlib
import json
import hashlib
from pathlib import Path
from loguru import logger

import chromadb

from nakama_kun.config.memory import MemorySettings
from nakama_kun.config.rag import RAGSettings
from nakama_kun.rag import get_embedding_provider
from nakama_kun.rag.vector_store import ChromaEmbeddingWrapper
from nakama_kun.memory.models import SuccessfulTask, FailureRecord
from nakama_kun.memory.sqlite_store import MemoryStore


class MemoryIndexer:
    """Indexes memory events into the local vector database collections."""

    def __init__(self, store: MemoryStore, workspace_root: str | Path | None = None) -> None:
        self.store = store
        self.workspace_root = Path(workspace_root) if workspace_root else Path.cwd()

        mem_settings = MemorySettings()
        vector_db_path = mem_settings.memory_vector_db_path
        if not Path(vector_db_path).is_absolute():
            vector_db_path = self.workspace_root / vector_db_path

        rag_settings = RAGSettings()
        provider = get_embedding_provider(rag_settings)
        self.embedding_function = ChromaEmbeddingWrapper(provider)

        self.client = chromadb.PersistentClient(path=str(vector_db_path))
        self.collection_successes = self.client.get_or_create_collection(
            "nakama_memory_successes", embedding_function=self.embedding_function  # type: ignore
        )
        self.collection_failures = self.client.get_or_create_collection(
            "nakama_memory_failures", embedding_function=self.embedding_function  # type: ignore
        )
        self.collection_resolutions = self.client.get_or_create_collection(
            "nakama_memory_resolutions", embedding_function=self.embedding_function  # type: ignore
        )

    def index_success(self, task: SuccessfulTask) -> None:
        """Embeds and indexes a successful task goal and metadata."""
        try:
            # Generate deterministic document ID based on goal and timestamp
            doc_id = f"success_{hashlib.md5((task.goal + task.timestamp.isoformat()).encode()).hexdigest()}"
            self.collection_successes.upsert(
                ids=[doc_id],
                documents=[task.goal],
                metadatas=[{
                    "goal": task.goal,
                    "plan_summary": task.plan_summary,
                    "outcome": task.outcome,
                    "files_changed": json.dumps(task.files_changed),
                    "tools_used": json.dumps(task.tools_used),
                    "timestamp": task.timestamp.isoformat(),
                }]
            )
            logger.debug(f"MemoryIndexer: Indexed successful task: {task.goal[:40]}...")
        except Exception as e:
            logger.error(f"MemoryIndexer: Failed to index successful task: {e}")

    def index_failure(self, failure: FailureRecord) -> None:
        """Embeds and indexes a failure goal and resolution."""
        try:
            # Embed failure goal
            fail_id = f"failure_{hashlib.md5((failure.goal + failure.timestamp.isoformat()).encode()).hexdigest()}"
            self.collection_failures.upsert(
                ids=[fail_id],
                documents=[failure.goal],
                metadatas=[{
                    "goal": failure.goal,
                    "attempted_actions": json.dumps(failure.attempted_actions),
                    "failure_type": failure.failure_type,
                    "failure_message": failure.failure_message,
                    "resolution": failure.resolution,
                    "timestamp": failure.timestamp.isoformat(),
                }]
            )

            # Embed failure resolution
            if failure.resolution:
                res_id = f"resolution_{hashlib.md5((failure.resolution + failure.timestamp.isoformat()).encode()).hexdigest()}"
                self.collection_resolutions.upsert(
                    ids=[res_id],
                    documents=[failure.resolution],
                    metadatas=[{
                        "resolution": failure.resolution,
                        "goal": failure.goal,
                        "failure_message": failure.failure_message,
                        "timestamp": failure.timestamp.isoformat(),
                    }]
                )

            logger.debug(f"MemoryIndexer: Indexed failure record: {failure.goal[:40]}...")
        except Exception as e:
            logger.error(f"MemoryIndexer: Failed to index failure record: {e}")

    def rebuild_index(self) -> None:
        """Wipes the vector collections and indexes all records from the SQLite database."""
        logger.info("MemoryIndexer: Rebuilding memory vector collections from SQLite database...")

        # Delete existing collections
        for name in ("nakama_memory_successes", "nakama_memory_failures", "nakama_memory_resolutions"):
            with contextlib.suppress(Exception):
                self.client.delete_collection(name)

        # Re-create collections
        self.collection_successes = self.client.get_or_create_collection(
            "nakama_memory_successes", embedding_function=self.embedding_function  # type: ignore
        )
        self.collection_failures = self.client.get_or_create_collection(
            "nakama_memory_failures", embedding_function=self.embedding_function  # type: ignore
        )
        self.collection_resolutions = self.client.get_or_create_collection(
            "nakama_memory_resolutions", embedding_function=self.embedding_function  # type: ignore
        )

        try:
            # Re-index successes
            successes = self.store.get_successes()
            for task in successes:
                self.index_success(task)

            # Re-index failures
            failures = self.store.get_failures()
            for failure in failures:
                self.index_failure(failure)

            logger.info(f"MemoryIndexer: Rebuild complete. Indexed {len(successes)} successes and {len(failures)} failures.")
        except Exception as e:
            logger.error(f"MemoryIndexer: Error during index rebuild: {e}")
