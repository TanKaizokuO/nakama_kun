"""orchestration/goal_satisfaction.py — Deterministic goal-satisfaction detector.

Evaluates whether a user's retrieval-oriented task has been completed by
inspecting the current tool outputs, the EvidenceStore, and execution history.

Rules (keyed by TaskType / sub-task):

* **Directory listing** — satisfied when ``list_files`` or a ``run_command``
  returning a non-empty listing (ls / dir / find) succeeds.
* **File reading** — satisfied when ``read_file`` succeeds with non-empty
  output, OR a ``file_validation`` entry with ``source`` in
  ``{'tool_read', 'disk'}`` is present.
* **PDF explanation** — satisfied when ``search_vector_store`` or
  ``run_command`` that extracted PDF text succeeds with non-empty output.
* **Version query** — satisfied when a successful ``run_command`` output
  contains recognisable version tokens (numbers, "version", "v\\d").

For task types other than RETRIEVAL the detector always returns
``goal_satisfied=False`` (leaving the verdict to the Reviewer node).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from nakama_kun.orchestration.task_classifier import TaskType


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class GoalSatisfactionResult:
    """Outcome returned by :class:`GoalSatisfactionDetector`."""

    goal_satisfied: bool
    """``True`` when the detector is confident the goal has been met."""

    confidence: float
    """Confidence in [0.0, 1.0]. 1.0 = deterministically certain."""

    explanation: str
    """Human-readable explanation of the verdict."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Tools that perform directory listing
_LISTING_TOOLS: frozenset[str] = frozenset({"list_files"})

# Shell commands that produce directory listings
_LISTING_CMD_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bls\b"),
    re.compile(r"\bdir\b"),
    re.compile(r"\bfind\b"),
    re.compile(r"\btree\b"),
)

# Tools that read file content
_READ_TOOLS: frozenset[str] = frozenset({"read_file"})

# Tools / commands used for PDF extraction
_PDF_TOOLS: frozenset[str] = frozenset({"search_vector_store"})
_PDF_CMD_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bpdf\b", re.IGNORECASE),
    re.compile(r"\bpdftotext\b", re.IGNORECASE),
    re.compile(r"\bpypdf\b", re.IGNORECASE),
)

# Version-bearing patterns in command output
_VERSION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bversion\b", re.IGNORECASE),
    re.compile(r"v?\d+\.\d+(\.\d+)?"),
)


def _is_listing_cmd(cmd: str) -> bool:
    return any(p.search(cmd) for p in _LISTING_CMD_PATTERNS)


def _is_pdf_cmd(cmd: str) -> bool:
    return any(p.search(cmd) for p in _PDF_CMD_PATTERNS)


def _output_contains_version(output: str) -> bool:
    return any(p.search(output) for p in _VERSION_PATTERNS)


def _goal_is_version_query(goal: str) -> bool:
    """Return True if the goal text looks like a version / environment query."""
    lower = goal.lower()
    version_keywords = (
        "version",
        "which version",
        "what version",
        "python --version",
        "node --version",
        "npm --version",
        "uname",
        "installed",
    )
    return any(kw in lower for kw in version_keywords)


def _goal_is_pdf_related(goal: str) -> bool:
    lower = goal.lower()
    return ".pdf" in lower or "pdf" in lower or "explain" in lower


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class GoalSatisfactionDetector:
    """Evaluates whether a retrieval goal has been satisfied.

    Parameters
    ----------
    task:
        The original user task string (``AgentState["goal"]``).
    task_type:
        The classified :class:`~nakama_kun.orchestration.task_classifier.TaskType`.
    tool_outputs:
        The list of tool-result dicts accumulated during the current
        execution loop (``new_tool_results`` inside the executor).
    evidence_store:
        The structured :class:`~nakama_kun.orchestration.evidence.EvidenceStore`
        if it has been built already, otherwise ``None``.
    execution_history:
        Optional list of previous agent-history records
        (``AgentState["agent_history"]``).
    """

    def __init__(
        self,
        *,
        task: str,
        task_type: str | TaskType,
        tool_outputs: list[dict[str, Any]],
        evidence_store: Any | None = None,
        execution_history: list[dict[str, Any]] | None = None,
    ) -> None:
        self.task = task
        self.task_type = str(task_type)
        self.tool_outputs = tool_outputs
        self.evidence_store = evidence_store
        self.execution_history = execution_history or []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def detect(self) -> GoalSatisfactionResult:
        """Run the detection rules and return a :class:`GoalSatisfactionResult`."""
        if self.task_type != TaskType.RETRIEVAL:
            return GoalSatisfactionResult(
                goal_satisfied=False,
                confidence=1.0,
                explanation=(
                    f"Task type is '{self.task_type}', not RETRIEVAL. "
                    "Goal satisfaction is evaluated by the Reviewer node."
                ),
            )

        # Run each sub-detector; return the first match.
        for check in (
            self._check_directory_listing,
            self._check_file_reading,
            self._check_pdf_explanation,
            self._check_version_query,
        ):
            result = check()
            if result is not None:
                return result

        return GoalSatisfactionResult(
            goal_satisfied=False,
            confidence=0.5,
            explanation="No successful retrieval tool output was detected yet.",
        )

    # ------------------------------------------------------------------
    # Sub-detectors
    # ------------------------------------------------------------------

    def _check_directory_listing(self) -> GoalSatisfactionResult | None:
        """Detect whether a directory listing was successfully obtained."""
        # Check tool outputs for list_files
        for tr in self.tool_outputs:
            if tr.get("tool") in _LISTING_TOOLS and tr.get("success"):
                output = tr.get("content", "") or tr.get("output", "")
                if output and output.strip():
                    return GoalSatisfactionResult(
                        goal_satisfied=True,
                        confidence=1.0,
                        explanation=(
                            f"Directory listing obtained via tool "
                            f"'{tr['tool']}'. "
                            f"Output preview: {output[:120]!r}"
                        ),
                    )

        # Check command outputs for ls / dir / find
        for tr in self.tool_outputs:
            if tr.get("tool") == "run_command" and tr.get("success"):
                args = tr.get("arguments", {})
                cmd = args.get("cmd", "") if isinstance(args, dict) else ""
                if _is_listing_cmd(cmd):
                    output = tr.get("content", "") or tr.get("output", "")
                    if output and output.strip():
                        return GoalSatisfactionResult(
                            goal_satisfied=True,
                            confidence=1.0,
                            explanation=(
                                f"Directory listing obtained via command "
                                f"'{cmd}'. "
                                f"Output preview: {output[:120]!r}"
                            ),
                        )

        # Check evidence_store.command_outputs (built by Verifier)
        if self.evidence_store:
            for co in getattr(self.evidence_store, "command_outputs", []):
                if _is_listing_cmd(co.cmd) and co.success and co.output:
                    return GoalSatisfactionResult(
                        goal_satisfied=True,
                        confidence=1.0,
                        explanation=(
                            f"Directory listing confirmed in EvidenceStore "
                            f"via command '{co.cmd}'."
                        ),
                    )
            for to in getattr(self.evidence_store, "tool_outputs", []):
                if to.tool in _LISTING_TOOLS and to.success and to.output:
                    return GoalSatisfactionResult(
                        goal_satisfied=True,
                        confidence=1.0,
                        explanation=(
                            f"Directory listing confirmed in EvidenceStore "
                            f"via tool '{to.tool}'."
                        ),
                    )

        return None

    def _check_file_reading(self) -> GoalSatisfactionResult | None:
        """Detect whether a file's contents were successfully retrieved."""
        # Direct read_file tool success
        for tr in self.tool_outputs:
            if tr.get("tool") in _READ_TOOLS and tr.get("success"):
                output = tr.get("content", "") or tr.get("output", "")
                if output and output.strip():
                    args = tr.get("arguments", {})
                    path = (
                        args.get("path", "<unknown>")
                        if isinstance(args, dict)
                        else "<unknown>"
                    )
                    return GoalSatisfactionResult(
                        goal_satisfied=True,
                        confidence=1.0,
                        explanation=(
                            f"File contents of '{path}' retrieved successfully. "
                            f"Output preview: {output[:120]!r}"
                        ),
                    )

        # Evidence store file validations
        if self.evidence_store:
            for fv in getattr(self.evidence_store, "file_validations", []):
                if (
                    fv.exists
                    and fv.content
                    and fv.source in ("tool_read", "disk")
                ):
                    return GoalSatisfactionResult(
                        goal_satisfied=True,
                        confidence=1.0,
                        explanation=(
                            f"File '{fv.path}' content validated in EvidenceStore "
                            f"(source: {fv.source})."
                        ),
                    )
            for to in getattr(self.evidence_store, "tool_outputs", []):
                if to.tool in _READ_TOOLS and to.success and to.output:
                    return GoalSatisfactionResult(
                        goal_satisfied=True,
                        confidence=1.0,
                        explanation=(
                            f"File read confirmed in EvidenceStore via tool '{to.tool}'."
                        ),
                    )

        return None

    def _check_pdf_explanation(self) -> GoalSatisfactionResult | None:
        """Detect whether PDF text was successfully extracted."""
        if not _goal_is_pdf_related(self.task):
            return None

        # search_vector_store success (RAG-based PDF retrieval)
        for tr in self.tool_outputs:
            if tr.get("tool") in _PDF_TOOLS and tr.get("success"):
                output = tr.get("content", "") or tr.get("output", "")
                if output and output.strip():
                    return GoalSatisfactionResult(
                        goal_satisfied=True,
                        confidence=1.0,
                        explanation=(
                            f"PDF text retrieved via tool '{tr['tool']}'. "
                            f"Output preview: {output[:120]!r}"
                        ),
                    )

        # run_command with a pdf-related command
        for tr in self.tool_outputs:
            if tr.get("tool") == "run_command" and tr.get("success"):
                args = tr.get("arguments", {})
                cmd = args.get("cmd", "") if isinstance(args, dict) else ""
                if _is_pdf_cmd(cmd):
                    output = tr.get("content", "") or tr.get("output", "")
                    if output and output.strip():
                        return GoalSatisfactionResult(
                            goal_satisfied=True,
                            confidence=1.0,
                            explanation=(
                                f"PDF text extracted via command '{cmd}'. "
                                f"Output preview: {output[:120]!r}"
                            ),
                        )

        # Evidence store
        if self.evidence_store:
            for to in getattr(self.evidence_store, "tool_outputs", []):
                if to.tool in _PDF_TOOLS and to.success and to.output:
                    return GoalSatisfactionResult(
                        goal_satisfied=True,
                        confidence=1.0,
                        explanation=(
                            f"PDF retrieval confirmed in EvidenceStore via tool '{to.tool}'."
                        ),
                    )

        return None

    def _check_version_query(self) -> GoalSatisfactionResult | None:
        """Detect whether a version/environment query was answered."""
        if not _goal_is_version_query(self.task):
            return None

        for tr in self.tool_outputs:
            if tr.get("tool") == "run_command" and tr.get("success"):
                output = tr.get("content", "") or tr.get("output", "")
                if _output_contains_version(output):
                    args = tr.get("arguments", {})
                    cmd = args.get("cmd", "") if isinstance(args, dict) else ""
                    return GoalSatisfactionResult(
                        goal_satisfied=True,
                        confidence=1.0,
                        explanation=(
                            f"Version information obtained via command '{cmd}'. "
                            f"Output preview: {output[:120]!r}"
                        ),
                    )

        # Evidence store
        if self.evidence_store:
            for co in getattr(self.evidence_store, "command_outputs", []):
                if co.success and _output_contains_version(co.output):
                    return GoalSatisfactionResult(
                        goal_satisfied=True,
                        confidence=1.0,
                        explanation=(
                            f"Version information confirmed in EvidenceStore "
                            f"via command '{co.cmd}'."
                        ),
                    )

        return None


# ---------------------------------------------------------------------------
# Convenience function for use in executor loops
# ---------------------------------------------------------------------------


def check_goal_satisfaction(
    *,
    task: str,
    task_type: str | TaskType,
    tool_outputs: list[dict[str, Any]],
    evidence_store: Any | None = None,
    execution_history: list[dict[str, Any]] | None = None,
) -> GoalSatisfactionResult:
    """Convenience wrapper around :class:`GoalSatisfactionDetector`.

    Parameters match those of the class constructor; see its docstring for
    full parameter descriptions.
    """
    detector = GoalSatisfactionDetector(
        task=task,
        task_type=task_type,
        tool_outputs=tool_outputs,
        evidence_store=evidence_store,
        execution_history=execution_history,
    )
    return detector.detect()
