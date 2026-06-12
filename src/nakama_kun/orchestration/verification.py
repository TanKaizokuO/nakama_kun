"""orchestration/verification.py — Verification Layer between Executor and Reviewer.

After the Executor finishes its tool-calling loop this layer:
  1. Parses tool_results to extract file paths written/read by the executor.
  2. Reads each written file back from disk and records its content.
  3. Checks existence of every referenced file path.
  4. Captures full command outputs (exit code + stdout/stderr) from run_command calls.
  5. Snapshots the workspace directory tree for changed paths.
  6. Assembles a structured VerificationReport stored in AgentState.
  7. Pre-computes an OutcomeSignal using a goal-first decision hierarchy so the
     Reviewer receives a structured APPROVE/REJECT recommendation before seeing
     any raw tool history.

Decision hierarchy encoded in OutcomeSignal:
  PRIMARY   — Artifact existence: files on disk are the ground truth.
  SECONDARY — Test results: exit-code-0 commands confirm success.
  TERTIARY  — Tool history: intermediate failures are informational only;
              a failed intermediate tool superseded by a successful fallback
              MUST NOT cause rejection if the final artifact exists.

The Reviewer Node then evaluates this report — real evidence — instead of guessing
from opaque character counts.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nakama_kun.orchestration.test_parser import parse_test_results

if TYPE_CHECKING:
    from nakama_kun.orchestration.state import AgentState


# ---------------------------------------------------------------------------
# Report data structures
# ---------------------------------------------------------------------------

class FileArtifact:
    """Represents a file that was created or modified during execution."""

    __slots__ = ("path", "exists", "content_snippet", "size_bytes")

    def __init__(self, path: str, exists: bool, content_snippet: str, size_bytes: int) -> None:
        self.path = path
        self.exists = exists
        self.content_snippet = content_snippet
        self.size_bytes = size_bytes

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "exists": self.exists,
            "content_snippet": self.content_snippet,
            "size_bytes": self.size_bytes,
        }


class ExistenceCheck:
    """Records whether a referenced path exists on disk."""

    __slots__ = ("path", "exists")

    def __init__(self, path: str, exists: bool) -> None:
        self.path = path
        self.exists = exists

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "exists": self.exists}


class CommandResult:
    """Captures the full output of a run_command tool invocation."""

    __slots__ = ("cmd", "exit_code", "stdout_snippet", "success", "test_summary")

    def __init__(
        self,
        cmd: str,
        exit_code: int,
        stdout_snippet: str,
        success: bool,
        test_summary: dict[str, Any] | None = None,
    ) -> None:
        self.cmd = cmd
        self.exit_code = exit_code
        self.stdout_snippet = stdout_snippet
        self.success = success
        self.test_summary = test_summary

    def to_dict(self) -> dict[str, Any]:
        return {
            "cmd": self.cmd,
            "exit_code": self.exit_code,
            "stdout_snippet": self.stdout_snippet,
            "success": self.success,
            "test_summary": self.test_summary,
        }


@dataclass
class OutcomeSignal:
    """Deterministic pre-classification of task outcome using a goal-first hierarchy.

    The hierarchy is:
      PRIMARY   — Artifact existence (files on disk).
      SECONDARY — Test/command results (exit codes).
      TERTIARY  — Tool execution history (treated as informational only).

    An intermediate tool failure that was superseded by a successful fallback
    MUST NOT influence the recommendation if the final artifact exists on disk.
    """

    artifacts_exist: bool        # ≥1 file verified to exist on disk
    all_files_exist: bool        # every existence_check.exists is True
    any_file_missing: bool       # ≥1 existence_check.exists is False
    tests_passed: bool           # all commands succeeded (or no commands ran)
    any_test_failed: bool        # ≥1 command had exit_code != 0
    files_created_count: int
    files_missing_count: int
    commands_passed: int
    commands_failed: int
    recommendation: str          # "APPROVE" | "REJECT" | "UNCERTAIN"
    reason: str                  # human-readable rationale

    def to_header_text(self) -> str:
        """Render the signal as a compact header block for the reviewer prompt."""
        icon = {"APPROVE": "✅", "REJECT": "❌", "UNCERTAIN": "⚠️"}.get(
            self.recommendation, "⚠️"
        )
        lines = [
            "=== PRE-COMPUTED OUTCOME SIGNAL ===",
            f"  Recommendation : {icon} {self.recommendation}",
            f"  Reason         : {self.reason}",
            f"  Artifacts exist: {self.artifacts_exist} "
            f"({self.files_created_count} on disk, {self.files_missing_count} missing)",
            f"  Commands       : {self.commands_passed} passed, {self.commands_failed} failed",
            "=== END OUTCOME SIGNAL ===",
        ]
        return "\n".join(lines)


class VerificationReport:
    """Complete workspace verification snapshot produced after executor finishes."""

    def __init__(
        self,
        files_created: list[FileArtifact],
        files_modified: list[FileArtifact],
        existence_checks: list[ExistenceCheck],
        command_results: list[CommandResult],
        workspace_snapshot: list[str],
        summary: str,
        required_artifacts: list[str] = None,
    ) -> None:
        self.files_created = files_created
        self.files_modified = files_modified
        self.existence_checks = existence_checks
        self.command_results = command_results
        self.workspace_snapshot = workspace_snapshot
        self.summary = summary
        self.required_artifacts = required_artifacts or []

    # ------------------------------------------------------------------
    # Outcome pre-classification
    # ------------------------------------------------------------------

    def evaluate_outcome(self) -> OutcomeSignal:
        """Deterministically compute an :class:`OutcomeSignal` from this report.

        Decision hierarchy
        ------------------
        1. PRIMARY — Artifact existence.  If any file exists on disk (from
           files_created, files_modified, or existence_checks), the goal has
           produced a concrete artefact.  Intermediate tool failures are
           irrelevant — a fallback may have written the file.
        2. SECONDARY — Test / command results.  Exit-code-0 commands confirm
           the artefacts are correct; non-zero exit codes on test runners
           indicate failure.
        3. TERTIARY — Tool history.  Only consulted when neither artefacts nor
           commands provide a clear signal.
        """
        # --- count artefacts that physically exist on disk ---
        all_artifacts = [
            *self.files_created,
            *self.files_modified,
        ]
        existing_artifacts = [fa for fa in all_artifacts if fa.exists]
        files_created_count = len(existing_artifacts)

        # existence_checks cover paths that were not captured as FileArtifact
        # (e.g. fallback-written files referenced only in read_file calls)
        missing_from_checks = [
            ec for ec in self.existence_checks if not ec.exists
        ]
        # A file in files_created with exists=True already proves presence;
        # only count checks that aren't already covered by FileArtifact paths.
        artifact_paths = {fa.path for fa in all_artifacts}
        extra_missing = [
            ec for ec in missing_from_checks
            if ec.path not in artifact_paths
        ]
        files_missing_count = len(
            [fa for fa in all_artifacts if not fa.exists]
        ) + len(extra_missing)

        artifacts_exist = files_created_count > 0
        # all_files_exist is True when every referenced path is present
        all_files_exist = (
            files_missing_count == 0
            and (files_created_count > 0 or len(self.existence_checks) == 0)
        )
        any_file_missing = files_missing_count > 0

        # --- command results ---
        commands_passed = sum(1 for cr in self.command_results if cr.success)
        commands_failed = sum(1 for cr in self.command_results if not cr.success)
        any_test_failed = commands_failed > 0
        tests_passed = not any_test_failed  # vacuously True when no commands ran

        # Aggregate test counts if any commands had structured test results
        total_passed_tests = 0
        total_failed_tests = 0
        total_error_tests = 0
        total_skipped_tests = 0
        has_tests = False

        for cr in self.command_results:
            if cr.test_summary is not None:
                has_tests = True
                total_passed_tests += cr.test_summary["passed"]
                total_failed_tests += cr.test_summary["failed"]
                total_error_tests += cr.test_summary["errors"]
                total_skipped_tests += cr.test_summary["skipped"]

        # --- check required artifacts explicitly ---
        missing_required = []
        if self.required_artifacts:
            existing_full_paths = {fa.path for fa in existing_artifacts}
            for req in self.required_artifacts:
                found = False
                for ep in existing_full_paths:
                    if ep.endswith(req) or Path(ep).name == Path(req).name:
                        found = True
                        break
                if not found:
                    missing_required.append(req)

        # --- apply hierarchy ---
        if missing_required:
            rec = "REJECT"
            reason = f"Execution finished but required artifact(s) are missing: {', '.join(missing_required)}"
        elif artifacts_exist and not any_test_failed:
            rec = "APPROVE"
            if has_tests:
                test_details = f"; Tests: {total_passed_tests} passed, {total_failed_tests} failed, {total_error_tests} errors, {total_skipped_tests} skipped"
            else:
                test_details = f"; {commands_passed} command(s) passed" if commands_passed > 0 else ""
            reason = (
                f"{files_created_count} artifact(s) confirmed on disk"
                + test_details
                + ". Intermediate tool failures (if any) were superseded by fallbacks."
            )
        elif artifacts_exist and any_test_failed:
            rec = "REJECT"
            if has_tests:
                reason = (
                    f"Artifact(s) exist ({files_created_count} on disk) but "
                    f"tests failed: {total_passed_tests} passed, {total_failed_tests} failed, {total_error_tests} errors."
                )
            else:
                reason = (
                    f"Artifact(s) exist ({files_created_count} on disk) but "
                    f"{commands_failed} test/command(s) failed with non-zero exit code."
                )
        elif not artifacts_exist and any_file_missing:
            rec = "REJECT"
            reason = (
                f"No artifacts found on disk and {files_missing_count} "
                f"referenced file(s) confirmed missing."
            )
        elif not artifacts_exist and any_test_failed:
            rec = "REJECT"
            if has_tests:
                reason = (
                    f"No artifacts on disk and tests failed: {total_passed_tests} passed, {total_failed_tests} failed, {total_error_tests} errors."
                )
            else:
                reason = (
                    f"No artifacts on disk and {commands_failed} command(s) failed."
                )
        elif not artifacts_exist and len(self.existence_checks) == 0 and len(self.command_results) == 0:
            rec = "UNCERTAIN"
            reason = "No tools produced verifiable evidence. Cannot confirm goal completion."
        else:
            # commands passed but no files — might be a non-file-producing task
            rec = "APPROVE"
            reason = (
                f"{commands_passed} command(s) passed with exit code 0."
                " Goal may not require file artifacts."
            )

        return OutcomeSignal(
            artifacts_exist=artifacts_exist,
            all_files_exist=all_files_exist,
            any_file_missing=any_file_missing,
            tests_passed=tests_passed,
            any_test_failed=any_test_failed,
            files_created_count=files_created_count,
            files_missing_count=files_missing_count,
            commands_passed=commands_passed,
            commands_failed=commands_failed,
            recommendation=rec,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "files_created": [f.to_dict() for f in self.files_created],
            "files_modified": [f.to_dict() for f in self.files_modified],
            "existence_checks": [e.to_dict() for e in self.existence_checks],
            "command_results": [c.to_dict() for c in self.command_results],
            "workspace_snapshot": self.workspace_snapshot,
            "summary": self.summary,
        }

    def to_reviewer_text(self, max_content_chars: int = 2000) -> str:
        """Render the report as a structured text block for the reviewer prompt.

        The outcome signal is placed first so the LLM receives a clear
        structured recommendation before any raw evidence that may contain
        intermediate failure markers.
        """
        signal = self.evaluate_outcome()
        lines: list[str] = [
            signal.to_header_text(),
            "",
            "=== VERIFICATION REPORT ===",
        ]

        # --- Files Created ---
        lines.append(f"\n📁 FILES CREATED ({len(self.files_created)}):")
        if self.files_created:
            for fa in self.files_created:
                lines.append(f"  Path   : {fa.path}")
                lines.append(f"  Exists : {fa.exists}")
                lines.append(f"  Size   : {fa.size_bytes} bytes")
                snippet = fa.content_snippet[:max_content_chars]
                lines.append(f"  Content:\n---\n{snippet}\n---")
        else:
            lines.append("  (none)")

        # --- Files Modified ---
        lines.append(f"\n✏️  FILES MODIFIED ({len(self.files_modified)}):")
        if self.files_modified:
            for fa in self.files_modified:
                lines.append(f"  Path   : {fa.path}")
                lines.append(f"  Exists : {fa.exists}")
                lines.append(f"  Size   : {fa.size_bytes} bytes")
                snippet = fa.content_snippet[:max_content_chars]
                lines.append(f"  Content:\n---\n{snippet}\n---")
        else:
            lines.append("  (none)")

        # --- Existence Checks ---
        lines.append(f"\n🔍 FILE EXISTENCE CHECKS ({len(self.existence_checks)}):")
        for ec in self.existence_checks:
            status = "✅ EXISTS" if ec.exists else "❌ MISSING"
            lines.append(f"  {status}: {ec.path}")
        if not self.existence_checks:
            lines.append("  (none)")

        # --- Commands ---
        lines.append(f"\n⚙️  COMMAND RESULTS ({len(self.command_results)}):")
        if self.command_results:
            for cr in self.command_results:
                status = "✅ PASS" if cr.success else "❌ FAIL"
                lines.append(f"  [{status}] $ {cr.cmd}")
                lines.append(f"  Exit Code: {cr.exit_code}")
                if cr.test_summary:
                    ts = cr.test_summary
                    lines.append(
                        f"  Tests    : {ts['passed']} passed, {ts['failed']} failed, "
                        f"{ts['errors']} errors, {ts['skipped']} skipped (success: {ts['success']})"
                    )
                snippet = cr.stdout_snippet[:max_content_chars]
                lines.append(f"  Output:\n---\n{snippet}\n---")
        else:
            lines.append("  (no commands run)")

        # --- Workspace Snapshot ---
        lines.append(f"\n🗂️  WORKSPACE SNAPSHOT ({len(self.workspace_snapshot)} files):")
        if self.workspace_snapshot:
            for p in self.workspace_snapshot[:50]:  # cap at 50 entries
                lines.append(f"  {p}")
            if len(self.workspace_snapshot) > 50:
                lines.append(f"  ... and {len(self.workspace_snapshot) - 50} more")
        else:
            lines.append("  (empty)")

        lines.append("\n=== END VERIFICATION REPORT ===")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Path extraction helpers
# ---------------------------------------------------------------------------

# Patterns that appear in write_file / read_file tool outputs
_PATH_FROM_OUTPUT_RE = re.compile(r"'([^']+\.[a-zA-Z0-9_]+)'")


def _extract_path_from_write_output(content: str) -> str | None:
    """Extract the file path from a WriteFileTool output string.

    E.g.: "Successfully wrote 123 characters to '/workspace/foo.py'."
    """
    match = _PATH_FROM_OUTPUT_RE.search(content)
    return match.group(1) if match else None


def _extract_paths_from_arguments(arguments: dict[str, Any] | str) -> list[str]:
    """Extract any file path values from tool arguments."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return []
    paths = []
    for key in ("path", "file_path", "filepath", "filename", "dest"):
        val = arguments.get(key) if isinstance(arguments, dict) else None
        if val and isinstance(val, str):
            paths.append(val)
    return paths


def _read_file_artifact(
    path: str, workspace_root: str, previously_known: set[str]
) -> tuple[FileArtifact, bool]:
    """Read a file and return (FileArtifact, was_already_known_before_execution)."""
    resolved = Path(path) if Path(path).is_absolute() else Path(workspace_root) / path
    exists = resolved.exists()
    was_known = path in previously_known

    content_snippet = ""
    size_bytes = 0
    if exists:
        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
            size_bytes = len(content.encode("utf-8"))
            content_snippet = content
        except OSError as exc:
            content_snippet = f"[read error: {exc}]"

    return FileArtifact(
        path=str(resolved),
        exists=exists,
        content_snippet=content_snippet,
        size_bytes=size_bytes,
    ), was_known


def _snapshot_workspace(workspace_root: str, max_files: int = 200) -> list[str]:
    """Walk workspace and return a sorted list of relative file paths."""
    root = Path(workspace_root)
    paths: list[str] = []
    skip_dirs = {".git", "__pycache__", ".venv", ".mypy_cache", ".pytest_cache", ".ruff_cache", "node_modules"}
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune skipped dirs in-place
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            for fname in filenames:
                rel = str(Path(dirpath).relative_to(root) / fname)
                paths.append(rel)
                if len(paths) >= max_files:
                    return sorted(paths)
    except OSError:
        pass
    return sorted(paths)


# ---------------------------------------------------------------------------
# VerificationLayer
# ---------------------------------------------------------------------------

class VerificationLayer:
    """Inspects AgentState after executor finishes and builds a VerificationReport.

    Parameters
    ----------
    workspace_root:
        Absolute path to the agent workspace root.  Defaults to ``os.getcwd()``.
    """

    def __init__(self, workspace_root: str | None = None) -> None:
        self._workspace_root = workspace_root or os.getcwd()

    def run(self, state: AgentState) -> VerificationReport:
        """Produce a :class:`VerificationReport` from the current agent state."""
        tool_results: list[dict[str, Any]] = state.get("tool_results", [])

        files_created: list[FileArtifact] = []
        files_modified: list[FileArtifact] = []
        existence_checks: list[ExistenceCheck] = []
        command_results: list[CommandResult] = []

        seen_paths: set[str] = set()

        for entry in tool_results:
            tool_name: str = entry.get("tool", "")
            arguments: dict[str, Any] | str = entry.get("arguments", {})
            success: bool = entry.get("success", False)
            content: str = entry.get("content", "")

            # --- write_file: read the file back from disk ---
            if tool_name == "write_file":
                paths = _extract_paths_from_arguments(arguments)
                # Also try to parse path from the output string
                if not paths:
                    extracted = _extract_path_from_write_output(content)
                    if extracted:
                        paths = [extracted]

                for path in paths:
                    if path in seen_paths:
                        continue
                    seen_paths.add(path)
                    artifact, was_known = _read_file_artifact(
                        path, self._workspace_root, set()
                    )
                    if was_known:
                        files_modified.append(artifact)
                    else:
                        files_created.append(artifact)
                    existence_checks.append(
                        ExistenceCheck(path=artifact.path, exists=artifact.exists)
                    )
                    logger.debug(
                        f"[Verification] write_file: path={artifact.path} exists={artifact.exists}"
                    )

            # --- read_file: just record existence check ---
            elif tool_name == "read_file":
                paths = _extract_paths_from_arguments(arguments)
                for path in paths:
                    if path in seen_paths:
                        continue
                    seen_paths.add(path)
                    resolved = (
                        Path(path)
                        if Path(path).is_absolute()
                        else Path(self._workspace_root) / path
                    )
                    exists = resolved.exists()
                    existence_checks.append(ExistenceCheck(path=str(resolved), exists=exists))
                    logger.debug(
                        f"[Verification] read_file: path={resolved} exists={exists}"
                    )

            # --- run_command: extract exit code and output ---
            elif tool_name == "run_command":
                args = arguments if isinstance(arguments, dict) else {}
                if isinstance(arguments, str):
                    try:
                        args = json.loads(arguments)
                    except json.JSONDecodeError:
                        args = {}
                cmd: str = args.get("cmd", "<unknown>")

                # Extract JSON payload from tool results.
                # If tool failed, content starts with the 'ERROR: ' prefix, which is stripped here.
                json_content = content
                if content.startswith("ERROR: "):
                    json_content = content[len("ERROR: "):]

                is_json = False
                exit_code = 0 if success else 1
                stdout_val = ""
                stderr_val = ""

                try:
                    data = json.loads(json_content)
                    if isinstance(data, dict) and "exit_code" in data:
                        exit_code = data["exit_code"]
                        stdout_val = data.get("stdout", "")
                        stderr_val = data.get("stderr", "")
                        is_json = True
                except Exception:
                    pass

                if is_json:
                    combined = stdout_val
                    if stderr_val:
                        combined += "\n" + stderr_val

                    test_summary = parse_test_results(cmd, combined)
                    cmd_success = (exit_code == 0)
                    if test_summary is not None:
                        cmd_success = test_summary["success"]

                    command_results.append(
                        CommandResult(
                            cmd=cmd,
                            exit_code=exit_code,
                            stdout_snippet=combined,
                            success=cmd_success,
                            test_summary=test_summary,
                        )
                    )
                else:
                    # Fallback to old behavior
                    exit_code = 0 if success else 1
                    ec_match = re.search(r"Exit code:\s*(-?\d+)", content)
                    if ec_match:
                        exit_code = int(ec_match.group(1))

                    test_summary = parse_test_results(cmd, content)
                    cmd_success = success
                    if test_summary is not None:
                        cmd_success = test_summary["success"]

                    command_results.append(
                        CommandResult(
                            cmd=cmd,
                            exit_code=exit_code,
                            stdout_snippet=content,
                            success=cmd_success,
                            test_summary=test_summary,
                        )
                    )
                logger.debug(
                    f"[Verification] run_command: cmd={cmd!r} exit_code={exit_code} success={command_results[-1].success} has_tests={test_summary is not None}"
                )

            # --- list_files / search_files: note any paths in results ---
            elif tool_name in ("list_files", "search_files"):
                paths = _extract_paths_from_arguments(arguments)
                for path in paths:
                    if path in seen_paths:
                        continue
                    seen_paths.add(path)
                    resolved = (
                        Path(path)
                        if Path(path).is_absolute()
                        else Path(self._workspace_root) / path
                    )
                    existence_checks.append(
                        ExistenceCheck(path=str(resolved), exists=resolved.exists())
                    )

        # Workspace snapshot
        workspace_snapshot = _snapshot_workspace(self._workspace_root)

        # Build summary line
        n_created = len(files_created)
        n_modified = len(files_modified)
        n_cmds = len(command_results)
        n_pass = sum(1 for c in command_results if c.success)
        n_fail = n_cmds - n_pass
        summary = (
            f"{n_created} file(s) created, {n_modified} file(s) modified; "
            f"{n_cmds} command(s) run ({n_pass} passed, {n_fail} failed); "
            f"{len(workspace_snapshot)} total workspace files."
        )
        logger.info(f"[Verification] {summary}")

        return VerificationReport(
            files_created=files_created,
            files_modified=files_modified,
            existence_checks=existence_checks,
            command_results=command_results,
            workspace_snapshot=workspace_snapshot,
            summary=summary,
            required_artifacts=state.get("required_artifacts", []),
        )
