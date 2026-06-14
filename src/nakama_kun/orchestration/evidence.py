from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nakama_kun.orchestration.state import AgentState
    from nakama_kun.orchestration.verification import VerificationReport


class ToolOutputEvidence:
    """Preserves raw tool execution results."""

    __slots__ = ("tool", "arguments", "success", "output")

    def __init__(self, tool: str, arguments: dict[str, Any], success: bool, output: str) -> None:
        self.tool = tool
        self.arguments = arguments
        self.success = success
        self.output = output

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "arguments": self.arguments,
            "success": self.success,
            "output": self.output,
        }


class FileValidationEvidence:
    """Preserves validation and content evidence for files."""

    __slots__ = ("path", "exists", "content", "source")

    def __init__(self, path: str, exists: bool, content: str, source: str) -> None:
        """source: 'disk', 'tool_read', or 'tool_write'"""
        self.path = path
        self.exists = exists
        self.content = content
        self.source = source

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "exists": self.exists,
            "content": self.content,
            "source": self.source,
        }


class CommandOutputEvidence:
    """Preserves command execution output and status."""

    __slots__ = ("cmd", "exit_code", "output", "success")

    def __init__(self, cmd: str, exit_code: int, output: str, success: bool) -> None:
        self.cmd = cmd
        self.exit_code = exit_code
        self.output = output
        self.success = success

    def to_dict(self) -> dict[str, Any]:
        return {
            "cmd": self.cmd,
            "exit_code": self.exit_code,
            "output": self.output,
            "success": self.success,
        }


class TestOutputEvidence:
    """Preserves parsed test results."""

    __slots__ = ("cmd", "passed", "failed", "errors", "skipped", "success")

    def __init__(
        self,
        cmd: str,
        passed: int,
        failed: int,
        errors: int,
        skipped: int,
        success: bool,
    ) -> None:
        self.cmd = cmd
        self.passed = passed
        self.failed = failed
        self.errors = errors
        self.skipped = skipped
        self.success = success

    def to_dict(self) -> dict[str, Any]:
        return {
            "cmd": self.cmd,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "success": self.success,
        }


class RetrievalEvidence:
    """Preserves repository retrieval events and retrieved context details."""
    __slots__ = ("goal", "retrieved_files", "summaries", "relevance_scores")

    def __init__(self, goal: str, retrieved_files: list[str], summaries: dict[str, str], relevance_scores: dict[str, float]) -> None:
        self.goal = goal
        self.retrieved_files = retrieved_files
        self.summaries = summaries
        self.relevance_scores = relevance_scores

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "retrieved_files": self.retrieved_files,
            "summaries": self.summaries,
            "relevance_scores": self.relevance_scores,
        }


class TestingEvidence:
    """Preserves implementation testing execution results and recommendations."""
    __slots__ = ("passed", "failed", "skipped", "errors", "recommendations")

    def __init__(self, passed: int, failed: int, skipped: int, errors: int, recommendations: list[str]) -> None:
        self.passed = passed
        self.failed = failed
        self.skipped = skipped
        self.errors = errors
        self.recommendations = recommendations

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "errors": self.errors,
            "recommendations": self.recommendations,
        }


class EvidenceStore:
    """A persistent registry preserving execution and validation evidence."""

    def __init__(self) -> None:
        self.tool_outputs: list[ToolOutputEvidence] = []
        self.file_validations: list[FileValidationEvidence] = []
        self.command_outputs: list[CommandOutputEvidence] = []
        self.test_outputs: list[TestOutputEvidence] = []
        self.retrieval_evidence: list[RetrievalEvidence] = []
        self.testing_evidence: list[TestingEvidence] = []

    def add_tool_output(self, tool: str, arguments: dict[str, Any], success: bool, output: str) -> None:
        self.tool_outputs.append(ToolOutputEvidence(tool, arguments, success, output))

    def add_file_validation(self, path: str, exists: bool, content: str, source: str) -> None:
        self.file_validations.append(FileValidationEvidence(path, exists, content, source))

    def add_command_output(self, cmd: str, exit_code: int, output: str, success: bool) -> None:
        self.command_outputs.append(CommandOutputEvidence(cmd, exit_code, output, success))

    def add_test_output(
        self,
        cmd: str,
        passed: int,
        failed: int,
        errors: int,
        skipped: int,
        success: bool,
    ) -> None:
        self.test_outputs.append(
            TestOutputEvidence(cmd, passed, failed, errors, skipped, success)
        )

    def add_retrieval_evidence(
        self,
        goal: str,
        retrieved_files: list[str],
        summaries: dict[str, str],
        relevance_scores: dict[str, float],
    ) -> None:
        self.retrieval_evidence.append(
            RetrievalEvidence(goal, retrieved_files, summaries, relevance_scores)
        )

    def add_testing_evidence(
        self,
        passed: int,
        failed: int,
        skipped: int,
        errors: int,
        recommendations: list[str],
    ) -> None:
        self.testing_evidence.append(
            TestingEvidence(passed, failed, skipped, errors, recommendations)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_outputs": [t.to_dict() for t in self.tool_outputs],
            "file_validations": [f.to_dict() for f in self.file_validations],
            "command_outputs": [c.to_dict() for c in self.command_outputs],
            "test_outputs": [t.to_dict() for t in self.test_outputs],
            "retrieval_evidence": [r.to_dict() for r in self.retrieval_evidence],
            "testing_evidence": [t.to_dict() for t in self.testing_evidence],
        }


def build_evidence_store(
    state: AgentState,
    report: VerificationReport | None,
    workspace_root: str | None = None,
) -> EvidenceStore:
    """Constructs the EvidenceStore by aggregating state history and verification results."""
    store = EvidenceStore()
    w_root = workspace_root or os.getcwd()

    # 1. Process state["tool_results"]
    tool_results = state.get("tool_results", [])
    for r in tool_results:
        tool_name = r.get("tool", "")
        arguments = r.get("arguments", {})
        success = r.get("success", False)
        content = r.get("content", "")

        # Preserve raw tool output
        store.add_tool_output(
            tool=tool_name,
            arguments=arguments if isinstance(arguments, dict) else {},
            success=success,
            output=content,
        )

        # Preserve read_file and write_file contents at time of execution
        if tool_name == "read_file" and success:
            from nakama_kun.orchestration.verification import (
                _extract_paths_from_arguments,
            )

            paths = _extract_paths_from_arguments(arguments)
            for path in paths:
                resolved = (
                    Path(path)
                    if Path(path).is_absolute()
                    else Path(w_root) / path
                )
                store.add_file_validation(
                    path=str(resolved),
                    exists=True,
                    content=content,
                    source="tool_read",
                )
        elif tool_name == "write_file" and success:
            from nakama_kun.orchestration.verification import (
                _extract_path_from_write_output,
                _extract_paths_from_arguments,
            )

            paths = _extract_paths_from_arguments(arguments)
            if not paths:
                extracted = _extract_path_from_write_output(content)
                if extracted:
                    paths = [extracted]
            for path in paths:
                resolved = (
                    Path(path)
                    if Path(path).is_absolute()
                    else Path(w_root) / path
                )
                written_content = ""
                if isinstance(arguments, dict):
                    written_content = arguments.get("content", "")
                store.add_file_validation(
                    path=str(resolved),
                    exists=True,
                    content=written_content,
                    source="tool_write",
                )

    # 2. Process VerificationReport physical checks and test outcomes
    if report:
        all_physical_artifacts = report.files_created + report.files_modified
        for fa in all_physical_artifacts:
            store.add_file_validation(
                path=fa.path,
                exists=fa.exists,
                content=fa.content_snippet,
                source="disk",
            )

        # General existence checks
        for ec in report.existence_checks:
            if not any(
                fv.path == ec.path and fv.source == "disk"
                for fv in store.file_validations
            ):
                store.add_file_validation(
                    path=ec.path,
                    exists=ec.exists,
                    content="",
                    source="disk",
                )

        # Command and test results
        for cr in report.command_results:
            store.add_command_output(
                cmd=cr.cmd,
                exit_code=cr.exit_code,
                output=cr.stdout_snippet,
                success=cr.success,
            )
            if cr.test_summary:
                ts = cr.test_summary
                store.add_test_output(
                    cmd=cr.cmd,
                    passed=ts.get("passed", 0),
                    failed=ts.get("failed", 0),
                    errors=ts.get("errors", 0),
                    skipped=ts.get("skipped", 0),
                    success=ts.get("success", False),
                )

    # 3. Process retrieval_package
    retrieval_package = state.get("retrieval_package")
    if retrieval_package:
        if hasattr(retrieval_package, "retrieved_files"):
            store.add_retrieval_evidence(
                goal=state.get("goal", ""),
                retrieved_files=retrieval_package.retrieved_files,
                summaries=retrieval_package.summaries,
                relevance_scores=retrieval_package.relevance_scores,
            )
        elif isinstance(retrieval_package, dict):
            store.add_retrieval_evidence(
                goal=state.get("goal", ""),
                retrieved_files=retrieval_package.get("retrieved_files", []),
                summaries=retrieval_package.get("summaries", {}),
                relevance_scores=retrieval_package.get("relevance_scores", {}),
            )

    # 4. Process test_report
    test_report = state.get("test_report")
    if test_report:
        if hasattr(test_report, "passed"):
            store.add_testing_evidence(
                passed=test_report.passed,
                failed=test_report.failed,
                skipped=test_report.skipped,
                errors=test_report.errors,
                recommendations=test_report.recommendations,
            )
        elif isinstance(test_report, dict):
            store.add_testing_evidence(
                passed=test_report.get("passed", 0),
                failed=test_report.get("failed", 0),
                skipped=test_report.get("skipped", 0),
                errors=test_report.get("errors", 0),
                recommendations=test_report.get("recommendations", []),
            )

    return store
