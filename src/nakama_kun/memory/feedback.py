from __future__ import annotations

from loguru import logger
from nakama_kun.memory.retriever import ExperienceBundle
from nakama_kun.memory.sqlite_store import MemoryStore


class MemoryFeedbackService:
    """Updates memory usage statistics and preference confidence after task execution."""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def record_success_usage(self, goal: str) -> None:
        """Increments success_frequency for matching successes in SQLite."""
        try:
            self.store.increment_success_frequency(goal)
            logger.info(f"MemoryFeedbackService: Incremented success frequency for goal: {goal}")
        except Exception as e:
            logger.warning(f"MemoryFeedbackService: Failed to increment success frequency: {e}")

    def record_failure_usage(self, goal: str) -> None:
        """Increments failure_frequency for matching failures in SQLite."""
        try:
            self.store.increment_failure_frequency(goal)
            logger.info(f"MemoryFeedbackService: Incremented failure frequency for goal: {goal}")
        except Exception as e:
            logger.warning(f"MemoryFeedbackService: Failed to increment failure frequency: {e}")

    def boost_preference_confidence(self, key: str, delta: float = 0.05) -> None:
        """Boosts preference confidence up to a cap of 1.0."""
        try:
            prefs = self.store.get_preferences()
            for p in prefs:
                if p.key == key:
                    new_conf = min(1.0, p.confidence + delta)
                    self.store.update_preference_confidence(key, new_conf)
                    logger.info(f"MemoryFeedbackService: Boosted preference '{key}' confidence to {new_conf:.2f}")
                    break
        except Exception as e:
            logger.warning(f"MemoryFeedbackService: Failed to boost preference confidence for key '{key}': {e}")

    def update_from_bundle(self, goal: str, bundle: ExperienceBundle) -> None:
        """Convenience method to update usage statistics for all elements of an ExperienceBundle."""
        for s in bundle.similar_successes:
            self.record_success_usage(s.goal)
        
        for f in bundle.similar_failures:
            self.record_failure_usage(f.goal)

        for p in bundle.user_preferences:
            self.boost_preference_confidence(p.key)
