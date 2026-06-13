from __future__ import annotations

import json
from datetime import datetime, UTC
from pathlib import Path
from loguru import logger

from nakama_kun.memory.models import SuccessfulTask, FailureRecord, UserPreference
from nakama_kun.memory.sqlite_store import MemoryStore


class MemoryManager:
    """Manages long-term experience storage and user preference learning."""

    def __init__(self, store: MemoryStore, workspace_root: str | Path | None = None) -> None:
        self.store = store
        self.workspace_root = Path(workspace_root) if workspace_root else None
        from nakama_kun.memory.indexer import MemoryIndexer
        self.indexer = MemoryIndexer(self.store, workspace_root=self.workspace_root)

    def save_successful_task(
        self,
        goal: str,
        plan_summary: str,
        files_changed: list[str],
        tools_used: list[str],
        outcome: str,
    ) -> None:
        """Saves a successfully completed task experience after checking for duplicates."""
        task = SuccessfulTask(
            goal=goal,
            plan_summary=plan_summary,
            files_changed=files_changed,
            tools_used=tools_used,
            outcome=outcome,
            timestamp=datetime.now(UTC),
        )

        # Deduplicate: check if matching goal + outcome already exists
        try:
            for s in self.store.get_successes():
                if s.goal == task.goal and s.outcome == task.outcome:
                    logger.info("MemoryManager: Duplicate successful task detected. Skipping save.")
                    return
        except Exception as e:
            logger.warning(f"MemoryManager: Error checking for duplicate successes: {e}")

        try:
            self.store.save_success(task)
            logger.info("MemoryManager: Saved successful task.")
            self.indexer.index_success(task)
            from nakama_kun.memory.retriever import ExperienceRetriever
            ExperienceRetriever.clear_cache()
        except Exception as e:
            logger.error(f"MemoryManager: Failed to save successful task: {e}")

        # Learn preferences from this successful run
        self.learn_preferences(goal)

    def save_failure_record(
        self,
        goal: str,
        attempted_actions: list[str],
        failure_type: str,
        failure_message: str,
        resolution: str,
    ) -> None:
        """Saves a task failure or rejection experience after checking for duplicates."""
        failure = FailureRecord(
            goal=goal,
            attempted_actions=attempted_actions,
            failure_type=failure_type,
            failure_message=failure_message,
            resolution=resolution,
            timestamp=datetime.now(UTC),
        )

        # Deduplicate: check if matching goal + failure_message already exists
        try:
            for f in self.store.get_failures():
                if f.goal == failure.goal and f.failure_message == failure.failure_message:
                    logger.info("MemoryManager: Duplicate failure record detected. Skipping save.")
                    return
        except Exception as e:
            logger.warning(f"MemoryManager: Error checking for duplicate failures: {e}")

        try:
            self.store.save_failure(failure)
            logger.info("MemoryManager: Saved failure record.")
            self.indexer.index_failure(failure)
            from nakama_kun.memory.retriever import ExperienceRetriever
            ExperienceRetriever.clear_cache()
        except Exception as e:
            logger.error(f"MemoryManager: Failed to save failure record: {e}")

    def learn_preferences(self, goal: str) -> None:
        """Extracts and merges user preferences from the user goal and workspace dependencies."""
        extracted_prefs: list[tuple[str, str, str]] = []

        # 1. Analyze goal text
        goal_lower = goal.lower()
        if "strict typing" in goal_lower or "strict_typing" in goal_lower:
            extracted_prefs.append(("typing", "strict", "user_goal"))
        if "ruff" in goal_lower:
            extracted_prefs.append(("linter", "ruff", "user_goal"))
        if "pytest" in goal_lower:
            extracted_prefs.append(("testing", "pytest", "user_goal"))
        if "fastapi" in goal_lower:
            extracted_prefs.append(("framework", "fastapi", "user_goal"))
        if "pydantic" in goal_lower:
            extracted_prefs.append(("validation", "pydantic", "user_goal"))

        # 2. Analyze dependencies from workspace_snapshot.json
        dependencies = self._load_dependencies()
        for dep in dependencies:
            dep_lower = dep.lower()
            # We want to match exactly or as a token to avoid prefix mismatches
            # e.g., "ruff", "pytest", "fastapi", "pydantic"
            if "ruff" in dep_lower:
                extracted_prefs.append(("linter", "ruff", "project_dependencies"))
            if "pytest" in dep_lower:
                extracted_prefs.append(("testing", "pytest", "project_dependencies"))
            if "fastapi" in dep_lower:
                extracted_prefs.append(("framework", "fastapi", "project_dependencies"))
            if "pydantic" in dep_lower:
                extracted_prefs.append(("validation", "pydantic", "project_dependencies"))

        if not extracted_prefs:
            return

        # 3. Merge extracted preferences into the store
        try:
            existing_prefs = {p.key: p for p in self.store.get_preferences()}
        except Exception as e:
            logger.warning(f"MemoryManager: Failed to fetch existing preferences for merging: {e}")
            existing_prefs = {}

        for key, value, source in extracted_prefs:
            if key in existing_prefs:
                existing = existing_prefs[key]
                if existing.value == value:
                    new_confidence = min(1.0, existing.confidence + 0.1)
                    updated_pref = UserPreference(
                        key=key,
                        value=value,
                        confidence=new_confidence,
                        source=source,
                        updated_at=datetime.now(UTC),
                    )
                    self.store.save_preference(updated_pref)
                    # Update local dict in case the same key is processed again in the same batch
                    existing_prefs[key] = updated_pref
                else:
                    new_confidence = existing.confidence - 0.2
                    if new_confidence < 0.0:
                        # Overwrite with the new preference
                        updated_pref = UserPreference(
                            key=key,
                            value=value,
                            confidence=0.5,
                            source=source,
                            updated_at=datetime.now(UTC),
                        )
                        self.store.save_preference(updated_pref)
                        existing_prefs[key] = updated_pref
                    else:
                        # Retain existing value, but decrement confidence
                        updated_pref = UserPreference(
                            key=key,
                            value=existing.value,
                            confidence=new_confidence,
                            source=existing.source,
                            updated_at=datetime.now(UTC),
                        )
                        self.store.save_preference(updated_pref)
                        existing_prefs[key] = updated_pref
            else:
                new_pref = UserPreference(
                    key=key,
                    value=value,
                    confidence=0.5,
                    source=source,
                    updated_at=datetime.now(UTC),
                )
                self.store.save_preference(new_pref)
                existing_prefs[key] = new_pref

    def _load_dependencies(self) -> list[str]:
        """Loads dependencies list from .workspace/workspace_snapshot.json if available."""
        if not self.workspace_root:
            return []
        snapshot_path = self.workspace_root / ".workspace" / "workspace_snapshot.json"
        if not snapshot_path.exists():
            return []
        try:
            with open(snapshot_path, encoding="utf-8") as f:
                data = json.load(f)
                return data.get("dependencies", [])
        except Exception as e:
            logger.warning(f"MemoryManager: Failed to read workspace snapshot: {e}")
            return []
