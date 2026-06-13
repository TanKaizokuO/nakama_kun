"""tests/test_verification.py — Tests for the VerificationLayer and verifier node.

Covers:
  - VerificationLayer correctly reads created files from disk
  - VerificationLayer captures command exit codes and output
  - VerificationLayer marks missing files as exists=False
  - VerificationLayer produces a coherent VerificationReport
  - VerificationReport.to_reviewer_text() renders all sections
  - make_verifier_node updates AgentState.verification_report
  - Reviewer approves when verification report shows files + passing tests
  - Reviewer rejects when verification report shows missing files / failures
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nakama_kun.ai.models.response import AIResponse
from nakama_kun.ai.services.chat_service import ChatService
from nakama_kun.orchestration.nodes import make_reviewer_node, make_verifier_node
from nakama_kun.orchestration.state import AgentState
from nakama_kun.orchestration.verification import (
    CommandResult,
    ExistenceCheck,
    FileArtifact,
    VerificationLayer,
    VerificationReport,
    _extract_path_from_write_output,
    _extract_paths_from_arguments,
    _snapshot_workspace,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_workspace(tmp_path: Path) -> str:
    """Return path to a temporary workspace directory."""
    return str(tmp_path)


@pytest.fixture()
def mock_chat_service() -> MagicMock:
    service = MagicMock(spec=ChatService)
    service.provider = MagicMock()
    service.provider.generate = AsyncMock()
    service.chat_with_tools = AsyncMock()
    return service


def _make_state(
    tool_results: list[dict],
    workspace_root: str | None = None,
) -> AgentState:
    """Build a minimal AgentState for verification tests."""
    return {
        "goal": "Write a calculator module",
        "plan": None,
        "messages": [],
        "tool_results": tool_results,
        "verification_report": None,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "reviewing",
    }


# ---------------------------------------------------------------------------
# Unit tests — helper functions
# ---------------------------------------------------------------------------


def test_extract_path_from_write_output_success() -> None:
    content = "Successfully wrote 123 characters to '/workspace/src/foo.py'."
    assert _extract_path_from_write_output(content) == "/workspace/src/foo.py"


def test_extract_path_from_write_output_no_match() -> None:
    assert _extract_path_from_write_output("No path here") is None


def test_extract_paths_from_arguments_dict() -> None:
    paths = _extract_paths_from_arguments({"path": "src/bar.py", "content": "hello"})
    assert paths == ["src/bar.py"]


def test_extract_paths_from_arguments_json_string() -> None:
    import json

    args_str = json.dumps({"path": "tests/test_bar.py"})
    paths = _extract_paths_from_arguments(args_str)
    assert paths == ["tests/test_bar.py"]


def test_extract_paths_from_arguments_bad_json() -> None:
    paths = _extract_paths_from_arguments("{not json}")
    assert paths == []


def test_snapshot_workspace(tmp_workspace: str) -> None:
    root = Path(tmp_workspace)
    (root / "a.py").write_text("a")
    (root / "sub").mkdir()
    (root / "sub" / "b.py").write_text("b")
    # Hidden/skipped dirs should not appear
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "c.pyc").write_text("c")

    snapshot = _snapshot_workspace(tmp_workspace)
    assert "a.py" in snapshot
    assert "sub/b.py" in snapshot
    # __pycache__ skipped
    assert not any("__pycache__" in p for p in snapshot)


# ---------------------------------------------------------------------------
# VerificationLayer tests
# ---------------------------------------------------------------------------


def test_verification_layer_write_file_creates_artifact(tmp_workspace: str) -> None:
    """VerificationLayer reads an actually-written file from disk."""
    root = Path(tmp_workspace)
    target = root / "output" / "hello.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("print('hello')", encoding="utf-8")

    tool_results = [
        {
            "tool": "write_file",
            "arguments": {"path": str(target), "content": "print('hello')"},
            "success": True,
            "content": f"Successfully wrote 14 characters to '{target}'.",
        }
    ]

    layer = VerificationLayer(workspace_root=tmp_workspace)
    state = _make_state(tool_results, tmp_workspace)
    report = layer.run(state)

    assert len(report.files_created) == 1
    fa = report.files_created[0]
    assert fa.exists is True
    assert "print('hello')" in fa.content_snippet
    assert fa.size_bytes > 0


def test_verification_layer_missing_file_existence_false(tmp_workspace: str) -> None:
    """VerificationLayer marks files that don't exist as exists=False."""
    missing_path = os.path.join(tmp_workspace, "ghost.py")
    tool_results = [
        {
            "tool": "write_file",
            "arguments": {"path": missing_path, "content": "x"},
            "success": False,  # tool failed — file never written
            "content": f"ERROR: permission denied writing '{missing_path}'.",
        }
    ]

    layer = VerificationLayer(workspace_root=tmp_workspace)
    state = _make_state(tool_results, tmp_workspace)
    report = layer.run(state)

    # Existence check should record the file as missing
    missing_checks = [ec for ec in report.existence_checks if not ec.exists]
    assert len(missing_checks) >= 1
    assert any(missing_path in ec.path for ec in missing_checks)


def test_verification_layer_command_pass(tmp_workspace: str) -> None:
    """VerificationLayer records passing command exit code."""
    tool_results = [
        {
            "tool": "run_command",
            "arguments": {"cmd": "pytest tests/ -v"},
            "success": True,
            "content": "Exit code: 0\nOutput:\n5 passed in 0.42s",
        }
    ]

    layer = VerificationLayer(workspace_root=tmp_workspace)
    state = _make_state(tool_results, tmp_workspace)
    report = layer.run(state)

    assert len(report.command_results) == 1
    cr = report.command_results[0]
    assert cr.cmd == "pytest tests/ -v"
    assert cr.exit_code == 0
    assert cr.success is True
    assert "5 passed" in cr.stdout_snippet


def test_verification_layer_command_fail(tmp_workspace: str) -> None:
    """VerificationLayer records failing command exit code."""
    tool_results = [
        {
            "tool": "run_command",
            "arguments": {"cmd": "pytest tests/ -v"},
            "success": False,
            "content": "Exit code: 1\nOutput:\n2 failed, 3 passed in 0.5s",
        }
    ]

    layer = VerificationLayer(workspace_root=tmp_workspace)
    state = _make_state(tool_results, tmp_workspace)
    report = layer.run(state)

    cr = report.command_results[0]
    assert cr.exit_code == 1
    assert cr.success is False
    assert "2 failed" in cr.stdout_snippet


def test_verification_layer_summary_text(tmp_workspace: str) -> None:
    """VerificationLayer summary is correctly formatted."""
    root = Path(tmp_workspace)
    target = root / "calc.py"
    target.write_text("def add(a, b): return a + b", encoding="utf-8")

    tool_results = [
        {
            "tool": "write_file",
            "arguments": {"path": str(target), "content": "def add(a, b): return a + b"},
            "success": True,
            "content": f"Successfully wrote 27 characters to '{target}'.",
        },
        {
            "tool": "run_command",
            "arguments": {"cmd": "python -m pytest"},
            "success": True,
            "content": "Exit code: 0\nOutput:\n1 passed",
        },
    ]

    layer = VerificationLayer(workspace_root=tmp_workspace)
    state = _make_state(tool_results, tmp_workspace)
    report = layer.run(state)

    assert "1 file(s) created" in report.summary
    assert "1 command(s) run" in report.summary
    assert "(1 passed, 0 failed)" in report.summary


def test_verification_layer_workspace_snapshot(tmp_workspace: str) -> None:
    """VerificationLayer includes workspace files in snapshot."""
    root = Path(tmp_workspace)
    (root / "README.md").write_text("# hello")
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("pass")

    layer = VerificationLayer(workspace_root=tmp_workspace)
    state = _make_state([], tmp_workspace)
    report = layer.run(state)

    assert "README.md" in report.workspace_snapshot
    assert "src/main.py" in report.workspace_snapshot


# ---------------------------------------------------------------------------
# VerificationReport tests
# ---------------------------------------------------------------------------


def test_verification_report_to_reviewer_text_sections() -> None:
    """to_reviewer_text() renders all expected section headers."""
    report = VerificationReport(
        files_created=[
            FileArtifact(
                path="/ws/foo.py", exists=True, content_snippet="print('ok')", size_bytes=11
            )
        ],
        files_modified=[],
        existence_checks=[ExistenceCheck(path="/ws/foo.py", exists=True)],
        command_results=[
            CommandResult(
                cmd="pytest", exit_code=0, stdout_snippet="1 passed", success=True
            )
        ],
        workspace_snapshot=["foo.py"],
        summary="1 file created, 1 command passed.",
    )

    text = report.to_reviewer_text()
    assert "FILES CREATED" in text
    assert "FILES MODIFIED" in text
    assert "FILE EXISTENCE CHECKS" in text
    assert "COMMAND RESULTS" in text
    assert "WORKSPACE SNAPSHOT" in text
    assert "print('ok')" in text
    assert "1 passed" in text
    assert "✅ EXISTS" in text


def test_verification_report_to_dict() -> None:
    """to_dict() produces a plain serialisable structure."""
    report = VerificationReport(
        files_created=[FileArtifact("/a.py", True, "x", 1)],
        files_modified=[],
        existence_checks=[ExistenceCheck("/a.py", True)],
        command_results=[CommandResult("ls", 0, "a.py", True)],
        workspace_snapshot=["a.py"],
        summary="ok",
    )
    d = report.to_dict()
    assert d["files_created"][0]["path"] == "/a.py"
    assert d["existence_checks"][0]["exists"] is True
    assert d["command_results"][0]["exit_code"] == 0


# ---------------------------------------------------------------------------
# Verifier Node tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_verifier_node_stores_report(tmp_workspace: str) -> None:
    """make_verifier_node returns a node that stores a VerificationReport in state."""
    root = Path(tmp_workspace)
    target = root / "output.py"
    target.write_text("x = 1", encoding="utf-8")

    tool_results = [
        {
            "tool": "write_file",
            "arguments": {"path": str(target), "content": "x = 1"},
            "success": True,
            "content": f"Successfully wrote 5 characters to '{target}'.",
        }
    ]

    verifier_node = make_verifier_node(workspace_root=tmp_workspace)
    state = _make_state(tool_results, tmp_workspace)
    result = await verifier_node(state)

    assert "verification_report" in result
    assert result["verification_report"] is not None
    assert result["status"] == "reviewing"
    report = result["verification_report"]
    assert isinstance(report, VerificationReport)
    assert len(report.files_created) == 1


@pytest.mark.anyio
async def test_verifier_node_no_tools(tmp_workspace: str) -> None:
    """Verifier node handles empty tool_results gracefully."""
    verifier_node = make_verifier_node(workspace_root=tmp_workspace)
    state = _make_state([], tmp_workspace)
    result = await verifier_node(state)

    report = result["verification_report"]
    assert report.files_created == []
    assert report.files_modified == []
    assert report.command_results == []


# ---------------------------------------------------------------------------
# Reviewer Node with VerificationReport tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reviewer_approves_with_positive_verification(
    mock_chat_service: MagicMock,
) -> None:
    """Reviewer approves when verification report shows files exist and tests pass."""
    mock_response = MagicMock(spec=AIResponse)
    mock_response.content = "[APPROVED]\nFile calc.py exists with correct content and tests pass."
    mock_chat_service.provider.generate.return_value = mock_response

    reviewer_node = make_reviewer_node(mock_chat_service)

    # Build a state with a positive verification report
    report = VerificationReport(
        files_created=[
            FileArtifact("/ws/calc.py", True, "def add(a, b): return a + b", 27)
        ],
        files_modified=[],
        existence_checks=[ExistenceCheck("/ws/calc.py", True)],
        command_results=[
            CommandResult("pytest tests/ -v", 0, "5 passed in 0.42s", True)
        ],
        workspace_snapshot=["calc.py", "tests/test_calc.py"],
        summary="1 file created, 1 command passed.",
    )

    state: AgentState = {
        "goal": "Write a calculator module with tests",
        "plan": None,
        "messages": [],
        "tool_results": [],
        "verification_report": report,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "reviewing",
    }

    result = await reviewer_node(state)

    assert result["reviewer_feedback"] is None
    assert result["status"] == "done"
    # Verify the reviewer prompt includes new hierarchy sections
    call_args = mock_chat_service.provider.generate.call_args
    messages = call_args[0][0]
    prompt_text = messages[-1].content
    assert "VERIFICATION REPORT" in prompt_text
    assert "FILES CREATED" in prompt_text
    assert "COMMAND RESULTS" in prompt_text
    assert "PRE-COMPUTED OUTCOME SIGNAL" in prompt_text
    assert "PRIMARY" in prompt_text
    assert "SECONDARY" in prompt_text
    assert "TERTIARY" in prompt_text


@pytest.mark.anyio
async def test_reviewer_rejects_when_files_missing(
    mock_chat_service: MagicMock,
) -> None:
    """Reviewer rejects when verification report shows missing files."""
    mock_response = MagicMock(spec=AIResponse)
    mock_response.content = "[REJECTED]\n- calc.py is missing from disk\n- No tests found"
    mock_chat_service.provider.generate.return_value = mock_response

    reviewer_node = make_reviewer_node(mock_chat_service)

    report = VerificationReport(
        files_created=[],
        files_modified=[],
        existence_checks=[ExistenceCheck("/ws/calc.py", False)],  # file missing!
        command_results=[],
        workspace_snapshot=[],
        summary="0 files created, 0 commands run.",
    )

    state: AgentState = {
        "goal": "Write a calculator module",
        "plan": None,
        "messages": [],
        "tool_results": [],
        "verification_report": report,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "reviewing",
    }

    result = await reviewer_node(state)

    assert "[REJECTED]" in result["reviewer_feedback"]
    assert result["status"] == "planning"


@pytest.mark.anyio
async def test_reviewer_falls_back_to_raw_summary_when_no_report(
    mock_chat_service: MagicMock,
) -> None:
    """Reviewer falls back gracefully when verification_report is None."""
    mock_response = MagicMock(spec=AIResponse)
    mock_response.content = "[APPROVED]\nFallback mode."
    mock_chat_service.provider.generate.return_value = mock_response

    reviewer_node = make_reviewer_node(mock_chat_service)

    state: AgentState = {
        "goal": "Write a file",
        "plan": None,
        "messages": [],
        "tool_results": [
            {"tool": "write_file", "success": True, "content": "Done.", "arguments": {}}
        ],
        "verification_report": None,  # no report
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "reviewing",
    }

    result = await reviewer_node(state)
    # Should still work — just uses fallback summary
    assert result["status"] == "done"

    call_args = mock_chat_service.provider.generate.call_args
    messages = call_args[0][0]
    prompt_text = messages[-1].content
    assert "No verification report available" in prompt_text


# ---------------------------------------------------------------------------
# OutcomeSignal / evaluate_outcome() unit tests
# ---------------------------------------------------------------------------


def _make_report(
    *,
    files_created: list[FileArtifact] | None = None,
    files_modified: list[FileArtifact] | None = None,
    existence_checks: list[ExistenceCheck] | None = None,
    command_results: list[CommandResult] | None = None,
) -> VerificationReport:
    """Helper to build a VerificationReport with sane defaults."""
    return VerificationReport(
        files_created=files_created or [],
        files_modified=files_modified or [],
        existence_checks=existence_checks or [],
        command_results=command_results or [],
        workspace_snapshot=[],
        summary="",
    )


def test_outcome_signal_approve_artifact_exists_no_commands() -> None:
    """PRIMARY criterion: artifact exists on disk → APPROVE (even with no commands)."""
    report = _make_report(
        files_created=[FileArtifact("/ws/calc.py", True, "def add(): pass", 20)],
        existence_checks=[ExistenceCheck("/ws/calc.py", True)],
    )
    signal = report.evaluate_outcome()
    assert signal.recommendation == "APPROVE"
    assert signal.artifacts_exist is True
    assert signal.files_created_count == 1
    assert signal.files_missing_count == 0


def test_outcome_signal_approve_artifact_exists_and_tests_pass() -> None:
    """PRIMARY + SECONDARY both positive → APPROVE."""
    report = _make_report(
        files_created=[FileArtifact("/ws/calc.py", True, "code", 4)],
        command_results=[CommandResult("pytest", 0, "5 passed", True)],
    )
    signal = report.evaluate_outcome()
    assert signal.recommendation == "APPROVE"
    assert signal.commands_passed == 1
    assert signal.commands_failed == 0
    assert "artifact" in signal.reason.lower() or "command" in signal.reason.lower()


def test_outcome_signal_approve_fallback_scenario() -> None:
    """PRIMARY criterion overrides TERTIARY: artifact exists even when
    the first write_file tool failed — a fallback produced the file."""
    # Simulate: write_file attempt 1 failed (success=False, file missing),
    # write_file attempt 2 succeeded via fallback (file now on disk)
    report = _make_report(
        # VerificationLayer reads the *final* state of the file from disk.
        # The second write_file attempt succeeded → file exists.
        files_created=[FileArtifact("/ws/calc.py", True, "def add(): pass", 20)],
        existence_checks=[
            ExistenceCheck("/ws/calc.py", True),  # final state: file exists
        ],
        command_results=[CommandResult("pytest", 0, "3 passed", True)],
    )
    signal = report.evaluate_outcome()
    # The intermediate failure is not visible in the report — only final disk state matters.
    assert signal.recommendation == "APPROVE"
    assert signal.artifacts_exist is True
    assert "superseded" in signal.reason.lower() or "artifact" in signal.reason.lower()


def test_outcome_signal_reject_all_files_missing() -> None:
    """Requested files confirmed missing → REJECT."""
    report = _make_report(
        files_created=[FileArtifact("/ws/calc.py", False, "", 0)],  # exists=False
        existence_checks=[ExistenceCheck("/ws/calc.py", False)],
    )
    signal = report.evaluate_outcome()
    assert signal.recommendation == "REJECT"
    assert signal.artifacts_exist is False
    assert signal.files_missing_count >= 1


def test_outcome_signal_reject_artifact_exists_but_tests_fail() -> None:
    """SECONDARY overrides PRIMARY when tests fail: artifact exists but test failed → REJECT."""
    report = _make_report(
        files_created=[FileArtifact("/ws/calc.py", True, "broken code", 11)],
        command_results=[CommandResult("pytest", 1, "2 FAILED", False)],
    )
    signal = report.evaluate_outcome()
    assert signal.recommendation == "REJECT"
    assert signal.any_test_failed is True
    assert signal.artifacts_exist is True  # file exists, but tests failed
    assert "failed" in signal.reason.lower()


def test_outcome_signal_reject_no_artifacts_commands_failed() -> None:
    """No artifacts and commands failed → REJECT."""
    report = _make_report(
        command_results=[CommandResult("make build", 2, "Error: compile failed", False)],
    )
    signal = report.evaluate_outcome()
    assert signal.recommendation == "REJECT"


def test_outcome_signal_uncertain_no_evidence() -> None:
    """No tools produced any verifiable evidence → UNCERTAIN."""
    report = _make_report()
    signal = report.evaluate_outcome()
    assert signal.recommendation == "UNCERTAIN"
    assert "cannot confirm" in signal.reason.lower()


def test_outcome_signal_approve_only_commands_passed() -> None:
    """Commands passed, no file artifacts (non-file-producing task) → APPROVE."""
    report = _make_report(
        command_results=[
            CommandResult("echo hello", 0, "hello", True),
            CommandResult("ls -la", 0, "total 4", True),
        ],
    )
    signal = report.evaluate_outcome()
    assert signal.recommendation == "APPROVE"
    assert signal.commands_passed == 2


def test_outcome_signal_header_text_contains_recommendation() -> None:
    """OutcomeSignal.to_header_text() includes recommendation and reason."""
    report = _make_report(
        files_created=[FileArtifact("/ws/f.py", True, "x", 1)],
    )
    signal = report.evaluate_outcome()
    header = signal.to_header_text()
    assert "APPROVE" in header
    assert "PRE-COMPUTED OUTCOME SIGNAL" in header
    assert signal.reason in header


def test_reviewer_text_contains_outcome_signal_before_report() -> None:
    """to_reviewer_text() places the outcome signal BEFORE the verification report."""
    report = _make_report(
        files_created=[FileArtifact("/ws/f.py", True, "x", 1)],
    )
    text = report.to_reviewer_text()
    signal_pos = text.index("PRE-COMPUTED OUTCOME SIGNAL")
    report_pos = text.index("VERIFICATION REPORT")
    assert signal_pos < report_pos, (
        "OutcomeSignal header must appear before the raw VERIFICATION REPORT section"
    )


# ---------------------------------------------------------------------------
# Regression tests — Fallback scenario end-to-end through reviewer node
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reviewer_approves_despite_intermediate_tool_failure(
    mock_chat_service: MagicMock,
) -> None:
    """Regression: reviewer MUST approve when final artifact exists on disk,
    even though an intermediate write_file attempt failed.

    Scenario:
      - write_file attempt 1: FAILED (permission denied)
      - run_command 'cp template.py calc.py': SUCCEEDED (fallback)
      - Final artifact: calc.py EXISTS on disk
      - Tests: PASS

    Expected: [APPROVED] — artifact existence (PRIMARY) overrides tool failure (TERTIARY).
    """
    mock_response = MagicMock(spec=AIResponse)
    mock_response.content = (
        "[APPROVED]\ncalc.py exists on disk with correct content. Tests passed."
    )
    mock_chat_service.provider.generate.return_value = mock_response

    reviewer_node = make_reviewer_node(mock_chat_service)

    # The VerificationLayer reads the *final* disk state.
    # calc.py exists → files_created has it with exists=True.
    report = VerificationReport(
        files_created=[
            FileArtifact("/ws/calc.py", True, "def add(a, b): return a + b", 28)
        ],
        files_modified=[],
        existence_checks=[
            ExistenceCheck("/ws/calc.py", True),   # ← artifact confirmed present
        ],
        command_results=[
            # The failed first attempt (write_file) is NOT in command_results —
            # it was a tool call, not a run_command. Only final commands appear.
            CommandResult("pytest tests/test_calc.py -v", 0, "3 passed in 0.21s", True),
        ],
        workspace_snapshot=["calc.py", "tests/test_calc.py"],
        summary="1 file created, 1 command passed.",
    )

    state: AgentState = {
        "goal": "Create a calculator module calc.py with add/subtract functions",
        "plan": None,
        "messages": [],
        "tool_results": [],
        "verification_report": report,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "reviewing",
    }

    result = await reviewer_node(state)

    # Must approve — artifact exists, tests pass
    assert result["reviewer_feedback"] is None
    assert result["status"] == "done"

    # Verify the prompt correctly embeds the APPROVE signal at the top
    call_args = mock_chat_service.provider.generate.call_args
    prompt_text = call_args[0][0][-1].content
    assert "PRE-COMPUTED OUTCOME SIGNAL" in prompt_text
    assert "APPROVE" in prompt_text
    # Hierarchy rules must be visible in prompt
    assert "PRIMARY" in prompt_text
    assert "TERTIARY" in prompt_text
    assert "intermediate" in prompt_text.lower() or "fallback" in prompt_text.lower()


@pytest.mark.anyio
async def test_reviewer_rejects_despite_some_tools_passing_when_artifact_missing(
    mock_chat_service: MagicMock,
) -> None:
    """Regression: reviewer MUST reject when artifact is confirmed MISSING even
    if some non-critical tools passed."""
    mock_response = MagicMock(spec=AIResponse)
    mock_response.content = (
        "[REJECTED]\n- calc.py is confirmed MISSING from disk\n- Goal not achieved"
    )
    mock_chat_service.provider.generate.return_value = mock_response

    reviewer_node = make_reviewer_node(mock_chat_service)

    report = VerificationReport(
        files_created=[FileArtifact("/ws/calc.py", False, "", 0)],  # ← missing!
        files_modified=[],
        existence_checks=[ExistenceCheck("/ws/calc.py", False)],
        command_results=[
            # An unrelated command passed — must not rescue a missing artifact
            CommandResult("echo done", 0, "done", True),
        ],
        workspace_snapshot=[],
        summary="0 files on disk, echo passed.",
    )

    state: AgentState = {
        "goal": "Create calc.py",
        "plan": None,
        "messages": [],
        "tool_results": [],
        "verification_report": report,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "reviewing",
    }

    result = await reviewer_node(state)
    assert "[REJECTED]" in result["reviewer_feedback"]
    assert result["status"] == "planning"

    # Signal should be REJECT
    call_args = mock_chat_service.provider.generate.call_args
    prompt_text = call_args[0][0][-1].content
    assert "REJECT" in prompt_text


@pytest.mark.anyio
async def test_reviewer_prompt_hierarchy_ordering(
    mock_chat_service: MagicMock,
) -> None:
    """Regression: PRIMARY must appear before SECONDARY, which must appear before TERTIARY
    in the reviewer prompt — ordering ensures the LLM follows the hierarchy."""
    mock_response = MagicMock(spec=AIResponse)
    mock_response.content = "[APPROVED]\nAll good."
    mock_chat_service.provider.generate.return_value = mock_response

    reviewer_node = make_reviewer_node(mock_chat_service)

    report = VerificationReport(
        files_created=[FileArtifact("/ws/x.py", True, "pass", 4)],
        files_modified=[],
        existence_checks=[],
        command_results=[],
        workspace_snapshot=[],
        summary="ok",
    )
    state: AgentState = {
        "goal": "Write x.py",
        "plan": None,
        "messages": [],
        "tool_results": [],
        "verification_report": report,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "reviewing",
    }

    await reviewer_node(state)

    call_args = mock_chat_service.provider.generate.call_args
    prompt_text = call_args[0][0][-1].content

    primary_pos = prompt_text.index("PRIMARY")
    secondary_pos = prompt_text.index("SECONDARY")
    tertiary_pos = prompt_text.index("TERTIARY")
    signal_pos = prompt_text.index("PRE-COMPUTED OUTCOME SIGNAL")

    assert primary_pos < secondary_pos < tertiary_pos, (
        "Hierarchy must be ordered PRIMARY → SECONDARY → TERTIARY"
    )
    assert signal_pos < primary_pos or signal_pos > tertiary_pos, (
        "Outcome signal must appear near the top of the prompt"
    )


def test_verification_layer_pytest_parsing(tmp_path: Path) -> None:
    """Verify VerificationLayer parses pytest results in run_command outputs."""
    layer = VerificationLayer(str(tmp_path))
    
    pytest_stdout = """
============================= test session starts ==============================
test_calculator.py ..F..                                                  [100%]
=================== 4 passed, 1 failed in 0.15s ===================
"""
    
    state: AgentState = {
        "goal": "Run tests",
        "plan": None,
        "messages": [],
        "tool_results": [
            {
                "tool": "run_command",
                "arguments": {"cmd": "pytest tests/"},
                "success": True,  # suppose command itself returned success but tests failed
                "content": pytest_stdout,
            }
        ],
        "verification_report": None,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "executing",
    }
    
    report = layer.run(state)
    assert len(report.command_results) == 1
    cr = report.command_results[0]
    
    assert cr.test_summary is not None
    assert cr.test_summary["passed"] == 4
    assert cr.test_summary["failed"] == 1
    assert cr.test_summary["errors"] == 0
    assert cr.test_summary["success"] is False
    # Verify overall success is updated to False because tests failed
    assert cr.success is False


def test_verification_layer_unittest_parsing(tmp_path: Path) -> None:
    """Verify VerificationLayer parses unittest results in run_command outputs."""
    layer = VerificationLayer(str(tmp_path))
    
    unittest_stdout = """
Ran 8 tests in 0.005s

OK (skipped=2)
"""
    
    state: AgentState = {
        "goal": "Run tests",
        "plan": None,
        "messages": [],
        "tool_results": [
            {
                "tool": "run_command",
                "arguments": {"cmd": "python -m unittest"},
                "success": True,
                "content": unittest_stdout,
            }
        ],
        "verification_report": None,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "executing",
    }
    
    report = layer.run(state)
    assert len(report.command_results) == 1
    cr = report.command_results[0]
    
    assert cr.test_summary is not None
    assert cr.test_summary["passed"] == 6
    assert cr.test_summary["failed"] == 0
    assert cr.test_summary["skipped"] == 2
    assert cr.test_summary["success"] is True
    assert cr.success is True


def test_verification_layer_failed_test_triggers_rejection(tmp_path: Path) -> None:
    """Verify failed tests in command results lead to a REJECT recommendation."""
    layer = VerificationLayer(str(tmp_path))
    
    pytest_stdout = """
============================= test session starts ==============================
=================== 3 passed, 1 error in 0.05s ===================
"""
    
    state: AgentState = {
        "goal": "Run tests",
        "plan": None,
        "messages": [],
        "tool_results": [
            {
                "tool": "run_command",
                "arguments": {"cmd": "pytest"},
                "success": True,
                "content": pytest_stdout,
            }
        ],
        "verification_report": None,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "executing",
    }
    
    report = layer.run(state)
    signal = report.evaluate_outcome()
    
    assert signal.recommendation == "REJECT"
    assert "tests failed" in signal.reason
    assert "3 passed" in signal.reason
    assert "1 errors" in signal.reason

