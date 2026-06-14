"""orchestration/task_classifier.py — Lightweight task-type classifier.

Determines whether a user goal matches a specific TaskType.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Tuple, List
from loguru import logger

# ---------------------------------------------------------------------------
# Task type Enum
# ---------------------------------------------------------------------------

class TaskType(str, Enum):
    ANALYSIS = "analysis"
    DOCUMENTATION = "documentation"
    CODE_MODIFICATION = "code_modification"
    # Future extensibility stubs:
    BUG_FIX = "bug_fix"
    FEATURE = "feature"
    REFACTOR = "refactor"
    RESEARCH = "research"
    RETRIEVAL = "retrieval"

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            return self.value.lower() == other.lower()
        if isinstance(other, Enum):
            return self.value.lower() == other.value.lower()
        return super().__eq__(other)

    def __ne__(self, other: Any) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return hash(self.value.lower())

    def __str__(self) -> str:
        return self.value


# For backward compatibility with older string checks or tests
TASK_TYPE_RETRIEVAL = TaskType.RETRIEVAL
TASK_TYPE_MODIFICATION = TaskType.CODE_MODIFICATION

# ---------------------------------------------------------------------------
# Rule-based Engine Definition
# ---------------------------------------------------------------------------

class ClassificationRule:
    """A rule mapping a set of patterns to a TaskType with scoring weight."""

    def __init__(self, task_type: TaskType, patterns: List[str], weight: float = 1.0):
        self.task_type = task_type
        self.compiled_patterns = []
        for pat in patterns:
            # If the pattern is alphanumeric, use word boundaries for matching
            if pat.isalnum():
                self.compiled_patterns.append(re.compile(rf"\b{pat}\b", re.IGNORECASE))
            else:
                # Literal match for multi-word or symbol-based phrases
                escaped = re.escape(pat)
                self.compiled_patterns.append(re.compile(escaped, re.IGNORECASE))
        self.weight = weight

    def match_score(self, text: str) -> float:
        """Calculate score based on matching patterns."""
        score = 0.0
        for pat in self.compiled_patterns:
            matches = pat.findall(text)
            if matches:
                score += self.weight * len(matches)
        return score

# ---------------------------------------------------------------------------
# Classifier Service
# ---------------------------------------------------------------------------

class TaskClassifier:
    """Centralized service for task classification."""

    def __init__(self) -> None:
        # Pre-compile patterns for core vs generic check to handle mixed requests
        self._core_code_mod = [re.compile(rf"\b{pat}\b", re.IGNORECASE) for pat in ["bug", "feature", "refactor", "implement", "fix", "patch", "scaffold", "migrate"]]
        self._generic_code_mod = [re.compile(rf"\b{pat}\b", re.IGNORECASE) for pat in ["modify", "change", "update", "add", "delete", "remove", "create", "write", "generate", "produce"]]
        self._doc_keywords = [re.compile(rf"\b{pat}\b", re.IGNORECASE) for pat in ["readme", "documentation", "document", "guide", "docs"]]

    def classify(self, goal: str) -> Tuple[TaskType, float, str]:
        """Classifies a task goal and returns the TaskType, confidence, and reasoning."""
        # Clean goal string
        normalised = goal.strip()

        # Core vs generic checks for dominance resolution
        has_core_code_mod = any(pat.search(normalised) for pat in self._core_code_mod)
        has_generic_code_mod = any(pat.search(normalised) for pat in self._generic_code_mod)
        has_doc_keywords = any(pat.search(normalised) for pat in self._doc_keywords)

        # Assemble modification patterns dynamically
        code_mod_patterns = ["bug", "feature", "refactor", "implement", "fix", "patch", "scaffold", "migrate", "write code", "edit code", "update code"]
        if has_generic_code_mod:
            # If there's generic code mod, but it also has docs keywords and lacks core code mod,
            # we classify it as pure document change, meaning generic keywords don't trigger CODE_MODIFICATION.
            if has_doc_keywords and not has_core_code_mod:
                pass
            else:
                code_mod_patterns.extend(["modify", "change", "update", "add", "delete", "remove", "create", "write", "generate", "produce"])

        # Define category rules
        rules = [
            ClassificationRule(
                TaskType.CODE_MODIFICATION,
                code_mod_patterns,
                weight=2.0
            ),
            ClassificationRule(
                TaskType.DOCUMENTATION,
                ["readme", "documentation", "document", "guide", "write doc", "generate doc", "create doc", "migration guide", "docs"],
                weight=1.5
            ),
            ClassificationRule(
                TaskType.ANALYSIS,
                [
                    "analyze", "analyse", "review", "explain", "audit", "summarize", "summarise",
                    "architecture", "codebase", "repository", "design pattern", "structure", "explain implementation"
                ],
                weight=1.2
            ),
            ClassificationRule(
                TaskType.RETRIEVAL,
                [
                    "list", "show files", "read file", "contents of", "what version", "version of", "python version", "node version",
                    "search", "grep", "find", "locate"
                ],
                weight=1.0
            ),
            ClassificationRule(
                TaskType.RESEARCH,
                [
                    "research", "search web", "google", "benchmark", "compare", "experiment", "investigate",
                    "literature survey", "deep-dive study", "explore the web"
                ],
                weight=1.0
            ),
        ]

        scores = {t: 0.0 for t in TaskType}
        for rule in rules:
            scores[rule.task_type] += rule.match_score(normalised)

        # Pick the highest scoring category
        max_score = 0.0
        best_type = TaskType.CODE_MODIFICATION
        for t, s in scores.items():
            if s > max_score:
                max_score = s
                best_type = t

        confidence = 0.0
        reason = ""
        if max_score > 0:
            confidence = min(1.0, max_score / 4.0)
            reason = f"Highest matching score ({max_score}) for {best_type.value}"
        else:
            confidence = 0.5
            best_type = TaskType.CODE_MODIFICATION
            reason = "No matching keywords; defaulted to code_modification"

        # Emit structured telemetry log
        logger.info(
            f"[Task Classification] task_type={best_type.value} reason={reason} confidence={confidence:.2f}"
        )

        return best_type, confidence, reason


def classify_task(goal: str) -> TaskType:
    """Return a TaskType enum value based on the goal string.

    Parameters
    ----------
    goal:
        The raw user goal string from ``AgentState["goal"]``.

    Returns
    -------
    TaskType
        One of the members of :class:`TaskType`.
    """
    classifier = TaskClassifier()
    task_type, _, _ = classifier.classify(goal)
    return task_type
