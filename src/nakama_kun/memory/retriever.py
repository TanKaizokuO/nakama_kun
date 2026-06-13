from __future__ import annotations

import json
import hashlib
from collections import Counter
from datetime import datetime, UTC
from pathlib import Path
from typing import Any
from loguru import logger
from pydantic import BaseModel, Field

import chromadb

from nakama_kun.config.memory import MemorySettings
from nakama_kun.config.rag import RAGSettings
from nakama_kun.rag import get_embedding_provider
from nakama_kun.rag.vector_store import ChromaEmbeddingWrapper
from nakama_kun.memory.models import SuccessfulTask, FailureRecord, UserPreference
from nakama_kun.memory.sqlite_store import MemoryStore


class ExperienceBundle(BaseModel):
    """Holds retrieved context about similar successes, failures, resolutions, and preferences."""

    similar_successes: list[SuccessfulTask] = Field(default_factory=list)
    similar_failures: list[FailureRecord] = Field(default_factory=list)
    learned_resolutions: list[str] = Field(default_factory=list)
    user_preferences: list[UserPreference] = Field(default_factory=list)

    def format_as_markdown(self) -> str:
        """Formats the experience bundle as a markdown block for agent prompt injection."""
        lines = []

        if self.similar_successes:
            lines.append("Similar Successes:")
            # Use unique goals to keep prompts clean
            seen = set()
            for s in self.similar_successes:
                goal_clean = s.goal.strip()
                if goal_clean not in seen:
                    seen.add(goal_clean)
                    lines.append(f"* {goal_clean}")
            lines.append("")

        if self.similar_failures:
            lines.append("Similar Failures:")
            seen = set()
            for f in self.similar_failures:
                msg_clean = f.failure_message.strip()
                if msg_clean not in seen:
                    seen.add(msg_clean)
                    lines.append(f"* {msg_clean}")
            lines.append("")

        if self.learned_resolutions:
            lines.append("Resolutions:")
            seen = set()
            for r in self.learned_resolutions:
                res_clean = r.strip()
                if res_clean not in seen:
                    seen.add(res_clean)
                    lines.append(f"* {res_clean}")
            lines.append("")

        if self.user_preferences:
            lines.append("Preferences:")
            for p in self.user_preferences:
                lines.append(f"* {p.key}: {p.value}")
            lines.append("")

        return "\n".join(lines).strip()


class ExperienceRetriever:
    """Retrieves and ranks semantic context from local memories and database logs."""

    def __init__(self, store: MemoryStore, workspace_root: str | Path | None = None) -> None:
        self.store = store
        self.workspace_root = Path(workspace_root) if workspace_root else Path.cwd()

        # Load settings
        mem_settings = MemorySettings()
        vector_db_path = mem_settings.memory_vector_db_path
        if not Path(vector_db_path).is_absolute():
            vector_db_path = self.workspace_root / vector_db_path

        # Setup collection structure using custom embedding provider
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

    _cache: dict[str, ExperienceBundle] = {}

    @classmethod
    def clear_cache(cls) -> None:
        """Wipes the global retrieval cache."""
        cls._cache.clear()

    def search_successes(self, query: str, limit: int = 5) -> list[SuccessfulTask]:
        """Queries successes by goal similarity and ranks by recency and frequency."""
        if not query or self.collection_successes.count() == 0:
            return []

        # Retrieve a slightly larger pool to rank
        n_results = min(limit * 3, self.collection_successes.count())
        results = self.collection_successes.query(query_texts=[query], n_results=n_results)

        if not results or "ids" not in results or not results["ids"] or not results["ids"][0]:
            return []

        # Get all successes from SQLite to calculate frequency
        try:
            all_successes = self.store.get_successes()
        except Exception as e:
            logger.warning(f"Retriever: Failed to fetch successes for frequency: {e}")
            all_successes = []

        goal_freqs = {}
        for s in all_successes:
            g = s.goal.lower().strip()
            goal_freqs[g] = goal_freqs.get(g, 0) + getattr(s, "success_frequency", 0) + 1
        now = datetime.now(UTC)

        scored_tasks = []
        ids = results["ids"][0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        for i in range(len(ids)):
            meta = metadatas[i]
            dist = distances[i] if i < len(distances) else 1.0

            try:
                task = SuccessfulTask(
                    goal=meta["goal"],
                    plan_summary=meta["plan_summary"],
                    files_changed=json.loads(meta["files_changed"]),
                    tools_used=json.loads(meta["tools_used"]),
                    outcome=meta["outcome"],
                    timestamp=datetime.fromisoformat(meta["timestamp"]),
                )
            except Exception as e:
                logger.warning(f"Retriever: Failed to rebuild task from metadata: {e}")
                continue

            # 1. Semantic Similarity
            sim_score = 1.0 / (1.0 + dist)

            # 2. Recency Score (7-day half life decay)
            elapsed_seconds = (now - task.timestamp).total_seconds()
            recency_score = 1.0 / (1.0 + elapsed_seconds / (7.0 * 86400.0))

            # 3. Success Frequency
            freq = goal_freqs.get(task.goal.lower().strip(), 1)
            frequency_score = min(1.0, (freq - 1) / 5.0) if freq > 1 else 0.0

            # Combined score: 50% Similarity, 30% Recency, 20% Frequency
            final_score = 0.5 * sim_score + 0.3 * recency_score + 0.2 * frequency_score
            scored_tasks.append((final_score, task))

        scored_tasks.sort(key=lambda x: x[0], reverse=True)
        return [task for _, task in scored_tasks[:limit]]

    def search_failures(self, query: str, limit: int = 5) -> list[FailureRecord]:
        """Queries failures by goal similarity and ranks by recency and occurrence frequency."""
        if not query or self.collection_failures.count() == 0:
            return []

        n_results = min(limit * 3, self.collection_failures.count())
        results = self.collection_failures.query(query_texts=[query], n_results=n_results)

        if not results or "ids" not in results or not results["ids"] or not results["ids"][0]:
            return []

        try:
            all_failures = self.store.get_failures()
        except Exception as e:
            logger.warning(f"Retriever: Failed to fetch failures for frequency: {e}")
            all_failures = []

        goal_freqs = {}
        for f in all_failures:
            g = f.goal.lower().strip()
            goal_freqs[g] = goal_freqs.get(g, 0) + getattr(f, "failure_frequency", 0) + 1
        now = datetime.now(UTC)

        scored_failures = []
        ids = results["ids"][0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        for i in range(len(ids)):
            meta = metadatas[i]
            dist = distances[i] if i < len(distances) else 1.0

            try:
                failure = FailureRecord(
                    goal=meta["goal"],
                    attempted_actions=json.loads(meta["attempted_actions"]),
                    failure_type=meta["failure_type"],
                    failure_message=meta["failure_message"],
                    resolution=meta["resolution"],
                    timestamp=datetime.fromisoformat(meta["timestamp"]),
                )
            except Exception as e:
                logger.warning(f"Retriever: Failed to rebuild failure from metadata: {e}")
                continue

            sim_score = 1.0 / (1.0 + dist)
            elapsed_seconds = (now - failure.timestamp).total_seconds()
            recency_score = 1.0 / (1.0 + elapsed_seconds / (7.0 * 86400.0))
            freq = goal_freqs.get(failure.goal.lower().strip(), 1)
            frequency_score = min(1.0, (freq - 1) / 5.0) if freq > 1 else 0.0

            final_score = 0.5 * sim_score + 0.3 * recency_score + 0.2 * frequency_score
            scored_failures.append((final_score, failure))

        scored_failures.sort(key=lambda x: x[0], reverse=True)
        return [f for _, f in scored_failures[:limit]]

    def search_preferences(self) -> list[UserPreference]:
        """Fetches stored preferences sorted by confidence."""
        try:
            prefs = self.store.get_preferences()
            return sorted(prefs, key=lambda p: p.confidence, reverse=True)
        except Exception as e:
            logger.warning(f"Retriever: Failed to fetch user preferences: {e}")
            return []

    def retrieve_experience(self, goal: str) -> ExperienceBundle:
        """Retrieves similar successes, failures, and resolutions, and user preferences with caching."""
        if not goal:
            return ExperienceBundle()

        if goal in self.__class__._cache:
            return self.__class__._cache[goal]

        # 1. Fetch similar successes
        successes = self.search_successes(goal, limit=3)

        # 2. Fetch similar failures
        failures = self.search_failures(goal, limit=3)

        # 3. Fetch similar resolutions semantically matching the goal
        resolutions = []
        if self.collection_resolutions.count() > 0:
            n_res = min(3, self.collection_resolutions.count())
            res_results = self.collection_resolutions.query(query_texts=[goal], n_results=n_res)
            if res_results and "metadatas" in res_results and res_results["metadatas"] and res_results["metadatas"][0]:
                for meta in res_results["metadatas"][0]:
                    if "resolution" in meta:
                        resolutions.append(meta["resolution"])

        # Also pull resolutions from matched failures if not already added
        for f in failures:
            if f.resolution and f.resolution not in resolutions:
                resolutions.append(f.resolution)

        # 4. Fetch sorted user preferences
        preferences = self.search_preferences()

        bundle = ExperienceBundle(
            similar_successes=successes,
            similar_failures=failures,
            learned_resolutions=resolutions[:5],  # Cap at top 5
            user_preferences=preferences,
        )

        self.__class__._cache[goal] = bundle
        return bundle
