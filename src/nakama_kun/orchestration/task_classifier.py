"""orchestration/task_classifier.py — Lightweight task-type classifier.

Determines whether a user goal is RETRIEVAL, ANALYSIS, CODE_MODIFICATION, or RESEARCH.
"""

from __future__ import annotations

from enum import StrEnum

# ---------------------------------------------------------------------------
# Task type Enum
# ---------------------------------------------------------------------------

class TaskType(StrEnum):
    RETRIEVAL = "RETRIEVAL"
    ANALYSIS = "ANALYSIS"
    CODE_MODIFICATION = "CODE_MODIFICATION"
    RESEARCH = "RESEARCH"


# For backward compatibility with older string checks or tests
TASK_TYPE_RETRIEVAL = TaskType.RETRIEVAL
TASK_TYPE_MODIFICATION = TaskType.CODE_MODIFICATION

# ---------------------------------------------------------------------------
# Keyword tables
# ---------------------------------------------------------------------------

_MODIFICATION_PHRASES: tuple[str, ...] = (
    "create",
    "write",
    "implement",
    "refactor",
    "edit",
    "modify",
    "change",
    "update",
    "add",
    "delete",
    "remove",
    "fix",
    "patch",
    "install",
    "deploy",
    "build",
    "run tests",
    "pytest",
    "unittest",
    "generate",
    "scaffold",
    "migrate",
)

_ANALYSIS_PHRASES: tuple[str, ...] = (
    "architecture",
    "design pattern",
    "dependency structure",
    "relationship between",
    "analyze repository",
    "analyse repository",
    "analyze codebase",
    "analyse codebase",
    "analyze project",
    "analyse project",
    "analyze architecture",
    "analyse architecture",
    "code review",
    "static analysis",
    "complexity analysis",
    "system design",
    "class hierarchy",
    "uml diagram",
    "analyze ",
    "analyse ",
)

_RESEARCH_PHRASES: tuple[str, ...] = (
    "research",
    "search web",
    "google",
    "benchmark",
    "compare",
    "experiment",
    "investigate",
    "literature survey",
    "deep-dive study",
    "explore the web",
)

_RETRIEVAL_PHRASES: tuple[str, ...] = (
    # directory / file listing
    "list",
    "ls",
    "dir ",
    "show files",
    "show folder",
    "show directory",
    "contents of",
    "what files",
    "what is in",
    "what's in",
    "whats in",
    # file reading
    "read",
    "cat ",
    "show me",
    "display",
    "print the",
    "output of",
    "view",
    # system / environment queries
    "what version",
    "which version",
    "version of",
    "python version",
    "node version",
    "npm version",
    "uname",
    "current directory",
    "working directory",
    "cwd",
    "pwd",
    "env",
    "environment variable",
    "what is the",
    "what's the",
    "whats the",
    "tell me",
    "find out",
    "check the",
    "check if",
    "inspect",
    "examine",
    "get the",
    "fetch the",
    "retrieve",
    "is installed",
    # search / grep
    "search",
    "grep",
    "find ",
    "locate",
    "where is",
    "which file",
    # explain / analyse (read-only)
    "explain",
    "describe",
    "summarise",
    "summarize",
    "show the content",
    "show content",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


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
    normalised = goal.lower()

    # 1. Research check (e.g. Google how to build...)
    for phrase in _RESEARCH_PHRASES:
        if phrase in normalised:
            return TaskType.RESEARCH

    # 2. Modification check
    for phrase in _MODIFICATION_PHRASES:
        if phrase in normalised:
            # "installed" or "installation" represents a query/state-check rather than action of installing.
            if phrase == "install" and ("installed" in normalised or "installation" in normalised):
                continue
            return TaskType.CODE_MODIFICATION

    # 3. Analysis check
    for phrase in _ANALYSIS_PHRASES:
        if phrase in normalised:
            return TaskType.ANALYSIS

    # 4. Retrieval check
    for phrase in _RETRIEVAL_PHRASES:
        if phrase in normalised:
            return TaskType.RETRIEVAL

    # Default: treat ambiguous/unknown goals as CODE_MODIFICATION
    return TaskType.CODE_MODIFICATION
