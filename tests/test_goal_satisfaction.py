"""tests/test_goal_satisfaction.py — Unit and integration tests for GoalSatisfactionDetector.

Coverage targets:
* Successful retrieval (directory listing, file read, PDF explanation, version query)
* Incomplete retrieval (tool ran but output empty, command failed)
* Missing file (read_file failure)
* Missing PDF (PDF goal but no PDF tool succeeded)
* Command failure (non-zero exit / success=False)
* Non-RETRIEVAL task types always return goal_satisfied=False
* EvidenceStore path (detector using pre-built evidence)
* check_goal_satisfaction convenience wrapper
* Integration: ExecutorAgent sets goal_satisfied via detector
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nakama_kun.agents.executor import ExecutorAgent
from nakama_kun.ai.models.message import ToolCall
from nakama_kun.ai.models.response import AIResponse, TokenUsage
from nakama_kun.orchestration.evidence import EvidenceStore
from nakama_kun.orchestration.goal_satisfaction import (
    GoalSatisfactionDetector,
    GoalSatisfactionResult,
    check_goal_satisfaction,
)
from nakama_kun.orchestration.task_classifier import TaskType
from nakama_kun.tools import ToolRegistry, ToolResult, ToolRouter
from nakama_kun.tools.interfaces import BaseTool


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _tr(
    tool: str,
    success: bool,
    content: str = "",
    arguments: dict | None = None,
) -> dict[str, Any]:
    """Build a minimal tool-result dict."""
    return {
        "tool": tool,
        "success": success,
        "content": content,
        "output": content,
        "arguments": arguments or {},
    }


def _run_cmd_tr(cmd: str, output: str, success: bool = True) -> dict[str, Any]:
    return _tr(
        tool="run_command",
        success=success,
        content=output,
        arguments={"cmd": cmd},
    )


def _make_evidence_store(
    *,
    cmd: str | None = None,
    cmd_output: str = "",
    cmd_success: bool = True,
    tool: str | None = None,
    tool_output: str = "",
    tool_success: bool = True,
    file_path: str | None = None,
    file_content: str = "",
    file_exists: bool = True,
    file_source: str = "tool_read",
) -> EvidenceStore:
    store = EvidenceStore()
    if cmd is not None:
        store.add_command_output(
            cmd=cmd,
            exit_code=0 if cmd_success else 1,
            output=cmd_output,
            success=cmd_success,
        )
    if tool is not None:
        store.add_tool_output(
            tool=tool,
            arguments={},
            success=tool_success,
            output=tool_output,
        )
    if file_path is not None:
        store.add_file_validation(
            path=file_path,
            exists=file_exists,
            content=file_content,
            source=file_source,
        )
    return store


# ---------------------------------------------------------------------------
# 1. Directory listing tests
# ---------------------------------------------------------------------------


class TestDirectoryListing:
    """Goal satisfied when requested directory contents are obtained."""

    def test_list_files_tool_success(self) -> None:
        tr = _tr("list_files", True, "file_a.py\nfile_b.py")
        result = check_goal_satisfaction(
            task="List contents of /tmp/test",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[tr],
        )
        assert result.goal_satisfied is True
        assert result.confidence == 1.0
        assert "list_files" in result.explanation

    def test_run_command_ls_success(self) -> None:
        tr = _run_cmd_tr("ls /tmp/test", "anime.mkv\nREADME.md")
        result = check_goal_satisfaction(
            task="List /tmp/test",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[tr],
        )
        assert result.goal_satisfied is True
        assert result.confidence == 1.0

    def test_run_command_find_success(self) -> None:
        tr = _run_cmd_tr("find /src -name '*.py'", "/src/main.py\n/src/utils.py")
        result = check_goal_satisfaction(
            task="List all Python files",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[tr],
        )
        assert result.goal_satisfied is True

    def test_run_command_dir_success(self) -> None:
        tr = _run_cmd_tr("dir /tmp", "Volume in drive C")
        result = check_goal_satisfaction(
            task="Show directory",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[tr],
        )
        assert result.goal_satisfied is True

    def test_listing_from_evidence_store(self) -> None:
        store = _make_evidence_store(cmd="ls /home/user", cmd_output="docs\nREADME.md")
        result = check_goal_satisfaction(
            task="List home directory",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[],
            evidence_store=store,
        )
        assert result.goal_satisfied is True

    def test_incomplete_listing_empty_output(self) -> None:
        """list_files ran but returned empty output — not satisfied."""
        tr = _tr("list_files", True, "")
        result = check_goal_satisfaction(
            task="List /empty",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[tr],
        )
        assert result.goal_satisfied is False

    def test_listing_tool_failed(self) -> None:
        tr = _tr("list_files", False, "Permission denied")
        result = check_goal_satisfaction(
            task="List /root",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[tr],
        )
        assert result.goal_satisfied is False

    def test_ls_command_failed(self) -> None:
        tr = _run_cmd_tr("ls /nonexistent", "No such file or directory", success=False)
        result = check_goal_satisfaction(
            task="List /nonexistent",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[tr],
        )
        assert result.goal_satisfied is False


# ---------------------------------------------------------------------------
# 2. File reading tests
# ---------------------------------------------------------------------------


class TestFileReading:
    """Goal satisfied when requested file contents are obtained."""

    def test_read_file_success(self) -> None:
        tr = _tr("read_file", True, "# Hello World", {"path": "/tmp/README.md"})
        result = check_goal_satisfaction(
            task="Read /tmp/README.md",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[tr],
        )
        assert result.goal_satisfied is True
        assert result.confidence == 1.0
        assert "README.md" in result.explanation

    def test_read_file_empty_output(self) -> None:
        """read_file returned nothing — not satisfied."""
        tr = _tr("read_file", True, "")
        result = check_goal_satisfaction(
            task="Read /tmp/empty.txt",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[tr],
        )
        assert result.goal_satisfied is False

    def test_missing_file_read_fails(self) -> None:
        """read_file failed — file missing."""
        tr = _tr("read_file", False, "FileNotFoundError: /tmp/missing.txt")
        result = check_goal_satisfaction(
            task="Read /tmp/missing.txt",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[tr],
        )
        assert result.goal_satisfied is False

    def test_file_reading_from_evidence_store_tool_read(self) -> None:
        store = _make_evidence_store(
            tool="read_file", tool_output="file contents here"
        )
        result = check_goal_satisfaction(
            task="Read config.yaml",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[],
            evidence_store=store,
        )
        assert result.goal_satisfied is True

    def test_file_reading_from_evidence_store_file_validation(self) -> None:
        store = _make_evidence_store(
            file_path="/home/user/notes.txt",
            file_content="My notes content",
            file_exists=True,
            file_source="tool_read",
        )
        result = check_goal_satisfaction(
            task="Read notes.txt",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[],
            evidence_store=store,
        )
        assert result.goal_satisfied is True

    def test_file_validation_missing_file(self) -> None:
        """File validation says exists=False — not satisfied."""
        store = _make_evidence_store(
            file_path="/tmp/missing.txt",
            file_content="",
            file_exists=False,
            file_source="disk",
        )
        result = check_goal_satisfaction(
            task="Read missing.txt",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[],
            evidence_store=store,
        )
        assert result.goal_satisfied is False


# ---------------------------------------------------------------------------
# 3. PDF explanation tests
# ---------------------------------------------------------------------------


class TestPDFExplanation:
    """Goal satisfied when PDF text is successfully extracted."""

    def test_search_vector_store_success(self) -> None:
        tr = _tr("search_vector_store", True, "Deepfake forensics involves...")
        result = check_goal_satisfaction(
            task="Explain Deepfake_Forensics.pdf",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[tr],
        )
        assert result.goal_satisfied is True

    def test_run_command_pdftotext_success(self) -> None:
        tr = _run_cmd_tr(
            "pdftotext report.pdf -",
            "This PDF discusses machine learning techniques...",
        )
        result = check_goal_satisfaction(
            task="Explain the PDF report.pdf",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[tr],
        )
        assert result.goal_satisfied is True

    def test_missing_pdf_no_tool_succeeded(self) -> None:
        """PDF goal, but search_vector_store failed."""
        tr = _tr("search_vector_store", False, "Collection not found")
        result = check_goal_satisfaction(
            task="Explain Deepfake_Forensics.pdf",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[tr],
        )
        assert result.goal_satisfied is False

    def test_missing_pdf_empty_output(self) -> None:
        """search_vector_store succeeded but returned nothing."""
        tr = _tr("search_vector_store", True, "")
        result = check_goal_satisfaction(
            task="Explain the quarterly report.pdf",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[tr],
        )
        assert result.goal_satisfied is False

    def test_pdf_goal_detected_by_evidence_store(self) -> None:
        store = _make_evidence_store(
            tool="search_vector_store", tool_output="Extracted text from PDF..."
        )
        result = check_goal_satisfaction(
            task="Explain the research paper.pdf",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[],
            evidence_store=store,
        )
        assert result.goal_satisfied is True

    def test_non_pdf_goal_skips_pdf_detector(self) -> None:
        """search_vector_store success on a non-PDF goal should NOT satisfy via PDF detector.
        But it may satisfy via file-reading detector (tool_outputs check), so we verify
        it does NOT match specifically through the PDF path when goal has no PDF keywords.
        """
        detector = GoalSatisfactionDetector(
            task="List directory contents",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[],
        )
        # _check_pdf_explanation must return None for non-PDF goals
        assert detector._check_pdf_explanation() is None


# ---------------------------------------------------------------------------
# 4. Version query tests
# ---------------------------------------------------------------------------


class TestVersionQuery:
    """Goal satisfied when command output contains version information."""

    def test_python_version_success(self) -> None:
        tr = _run_cmd_tr("python3 --version", "Python 3.12.3")
        result = check_goal_satisfaction(
            task="What Python version is installed?",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[tr],
        )
        assert result.goal_satisfied is True
        assert result.confidence == 1.0

    def test_node_version_success(self) -> None:
        tr = _run_cmd_tr("node --version", "v20.11.0")
        result = check_goal_satisfaction(
            task="Which version of Node.js is installed?",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[tr],
        )
        assert result.goal_satisfied is True

    def test_uname_version_success(self) -> None:
        tr = _run_cmd_tr("uname -r", "5.15.0-91-generic")
        result = check_goal_satisfaction(
            task="What is the uname version?",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[tr],
        )
        assert result.goal_satisfied is True

    def test_command_failure_no_satisfaction(self) -> None:
        """Command failed — version not obtained."""
        tr = _run_cmd_tr("python3 --version", "command not found", success=False)
        result = check_goal_satisfaction(
            task="What Python version is installed?",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[tr],
        )
        assert result.goal_satisfied is False

    def test_version_output_missing_version_pattern(self) -> None:
        """Command succeeded but output has no version-like content."""
        tr = _run_cmd_tr("python3 --version", "ok")
        result = check_goal_satisfaction(
            task="What Python version is installed?",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[tr],
        )
        assert result.goal_satisfied is False

    def test_version_from_evidence_store(self) -> None:
        store = _make_evidence_store(
            cmd="npm --version", cmd_output="9.8.1", cmd_success=True
        )
        result = check_goal_satisfaction(
            task="What npm version is installed?",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[],
            evidence_store=store,
        )
        assert result.goal_satisfied is True


# ---------------------------------------------------------------------------
# 5. Non-RETRIEVAL task types always return False
# ---------------------------------------------------------------------------


class TestNonRetrievalTypes:
    """For non-RETRIEVAL tasks, detector must always return goal_satisfied=False."""

    @pytest.mark.parametrize(
        "task_type",
        [TaskType.CODE_MODIFICATION, TaskType.ANALYSIS, TaskType.RESEARCH],
    )
    def test_non_retrieval_always_false(self, task_type: TaskType) -> None:
        tr = _tr("read_file", True, "some content")
        result = check_goal_satisfaction(
            task="Do something",
            task_type=task_type,
            tool_outputs=[tr],
        )
        assert result.goal_satisfied is False
        assert result.confidence == 1.0
        assert "not RETRIEVAL" in result.explanation or task_type.value in result.explanation


# ---------------------------------------------------------------------------
# 6. GoalSatisfactionResult dataclass
# ---------------------------------------------------------------------------


class TestGoalSatisfactionResult:
    def test_dataclass_fields(self) -> None:
        r = GoalSatisfactionResult(
            goal_satisfied=True, confidence=0.9, explanation="test"
        )
        assert r.goal_satisfied is True
        assert r.confidence == 0.9
        assert r.explanation == "test"

    def test_negative_result(self) -> None:
        r = GoalSatisfactionResult(
            goal_satisfied=False, confidence=0.5, explanation="nothing found"
        )
        assert r.goal_satisfied is False


# ---------------------------------------------------------------------------
# 7. Detector class interface tests
# ---------------------------------------------------------------------------


class TestGoalSatisfactionDetector:
    def test_no_tool_outputs_no_evidence(self) -> None:
        detector = GoalSatisfactionDetector(
            task="List files",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[],
        )
        result = detector.detect()
        assert result.goal_satisfied is False
        assert result.confidence == 0.5

    def test_confidence_is_1_on_success(self) -> None:
        tr = _tr("list_files", True, "file.txt")
        detector = GoalSatisfactionDetector(
            task="List files",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[tr],
        )
        result = detector.detect()
        assert result.confidence == 1.0

    def test_execution_history_accepted(self) -> None:
        history = [{"agent": "PlannerAgent", "thought": "planned"}]
        tr = _tr("read_file", True, "data", {"path": "/x.txt"})
        result = check_goal_satisfaction(
            task="Read /x.txt",
            task_type=TaskType.RETRIEVAL,
            tool_outputs=[tr],
            execution_history=history,
        )
        assert result.goal_satisfied is True


# ---------------------------------------------------------------------------
# 8. Integration: ExecutorAgent uses GoalSatisfactionDetector
# ---------------------------------------------------------------------------


def _make_ai_response(
    content: str | None = None,
    finish_reason: str = "stop",
    tool_calls: list[ToolCall] | None = None,
) -> AIResponse:
    return AIResponse(
        content=content,
        model="test-model",
        usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        finish_reason=finish_reason,
        latency=0.1,
        tool_calls=tool_calls,
    )


def _make_tool_call(name: str, arguments: dict, call_id: str = "call_1") -> ToolCall:
    return ToolCall(
        id=call_id,
        type="function",
        function={"name": name, "arguments": arguments},
    )


class DummyListFilesTool(BaseTool):
    name = "list_files"
    description = "List directory contents."
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, output="main.py\nREADME.md\nsetup.py")


class DummyReadFileTool(BaseTool):
    name = "read_file"
    description = "Read a file."
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, output="# Hello World")


class DummyFailReadFileTool(BaseTool):
    """read_file that always fails (simulates missing file)."""

    name = "read_file"
    description = "Read a file."
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=False, error="FileNotFoundError: file not found")


class DummyRunCommandTool(BaseTool):
    name = "run_command"
    description = "Run a shell command."
    parameters = {
        "type": "object",
        "properties": {"cmd": {"type": "string"}},
        "required": ["cmd"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        cmd = kwargs.get("cmd", "")
        if "--version" in cmd:
            return ToolResult(success=True, output="Python 3.12.3")
        return ToolResult(success=True, output="command output")


class DummyFailCommandTool(BaseTool):
    """run_command that always fails."""

    name = "run_command"
    description = "Run a shell command."
    parameters = {
        "type": "object",
        "properties": {"cmd": {"type": "string"}},
        "required": ["cmd"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=False, error="bash: command not found")


def _make_executor(tool: BaseTool) -> tuple[ExecutorAgent, MagicMock]:
    chat_service = MagicMock()
    registry = ToolRegistry()
    registry.register(tool)
    router = ToolRouter(registry)
    agent = ExecutorAgent(chat_service, registry, router)
    return agent, chat_service


def _base_state(goal: str, task_type: str = "RETRIEVAL") -> dict[str, Any]:
    return {
        "goal": goal,
        "task_type": task_type,
        "messages": [],
        "tool_results": [],
        "created_artifacts": [],
        "research_budget_remaining": 15,
        "delivery_mode": False,
        "goal_satisfied": False,
        "agent_history": [],
        "plan": None,
        "coder_proposals": [],
        "retry_memory": None,
    }


@pytest.mark.anyio
async def test_executor_directory_listing_sets_goal_satisfied() -> None:
    """Successful list_files → goal_satisfied=True via GoalSatisfactionDetector."""
    tc = _make_tool_call("list_files", {"path": "/tmp/project"})
    responses = [
        _make_ai_response(finish_reason="tool_calls", tool_calls=[tc]),
        _make_ai_response(content="Directory listed.", finish_reason="stop"),
    ]
    agent, chat_service = _make_executor(DummyListFilesTool())
    chat_service.chat_with_tools = AsyncMock(side_effect=responses)

    res = await agent.run(_base_state("List contents of /tmp/project"))

    assert res["goal_satisfied"] is True
    assert len(res["tool_results"]) == 1
    assert res["tool_results"][0]["tool"] == "list_files"
    assert res["tool_results"][0]["success"] is True


@pytest.mark.anyio
async def test_executor_file_read_sets_goal_satisfied() -> None:
    """Successful read_file → goal_satisfied=True."""
    tc = _make_tool_call("read_file", {"path": "README.md"})
    responses = [
        _make_ai_response(finish_reason="tool_calls", tool_calls=[tc]),
        _make_ai_response(content="File read.", finish_reason="stop"),
    ]
    agent, chat_service = _make_executor(DummyReadFileTool())
    chat_service.chat_with_tools = AsyncMock(side_effect=responses)

    res = await agent.run(_base_state("Read README.md"))

    assert res["goal_satisfied"] is True


@pytest.mark.anyio
async def test_executor_missing_file_does_not_satisfy() -> None:
    """Failed read_file → goal_satisfied=False."""
    tc = _make_tool_call("read_file", {"path": "/tmp/missing.txt"})
    responses = [
        _make_ai_response(finish_reason="tool_calls", tool_calls=[tc]),
        _make_ai_response(content="File not found.", finish_reason="stop"),
    ]
    agent, chat_service = _make_executor(DummyFailReadFileTool())
    chat_service.chat_with_tools = AsyncMock(side_effect=responses)

    res = await agent.run(_base_state("Read /tmp/missing.txt"))

    assert res["goal_satisfied"] is False
    assert res["tool_results"][0]["success"] is False


@pytest.mark.anyio
async def test_executor_command_failure_does_not_satisfy() -> None:
    """Failed run_command → goal_satisfied=False even for version query goal."""
    tc = _make_tool_call("run_command", {"cmd": "python3 --version"})
    responses = [
        _make_ai_response(finish_reason="tool_calls", tool_calls=[tc]),
        _make_ai_response(content="Command failed.", finish_reason="stop"),
    ]
    agent, chat_service = _make_executor(DummyFailCommandTool())
    chat_service.chat_with_tools = AsyncMock(side_effect=responses)

    res = await agent.run(_base_state("What Python version is installed?"))

    assert res["goal_satisfied"] is False


@pytest.mark.anyio
async def test_executor_version_query_sets_goal_satisfied() -> None:
    """Successful python3 --version → goal_satisfied=True for version query."""
    tc = _make_tool_call("run_command", {"cmd": "python3 --version"})
    responses = [
        _make_ai_response(finish_reason="tool_calls", tool_calls=[tc]),
        _make_ai_response(content="Python 3.12.3", finish_reason="stop"),
    ]
    agent, chat_service = _make_executor(DummyRunCommandTool())
    chat_service.chat_with_tools = AsyncMock(side_effect=responses)

    res = await agent.run(_base_state("What Python version is installed?"))

    assert res["goal_satisfied"] is True


@pytest.mark.anyio
async def test_executor_modification_task_no_early_termination() -> None:
    """For CODE_MODIFICATION tasks, read_file should NOT trigger goal_satisfied."""
    tc = _make_tool_call("read_file", {"path": "main.py"})
    # Both responses available — if early termination is wrong, only one call used
    responses = [
        _make_ai_response(finish_reason="tool_calls", tool_calls=[tc]),
        _make_ai_response(content="All done.", finish_reason="stop"),
    ]
    agent, chat_service = _make_executor(DummyReadFileTool())
    chat_service.chat_with_tools = AsyncMock(side_effect=responses)

    res = await agent.run(
        _base_state("Implement feature in main.py", task_type="CODE_MODIFICATION")
    )

    # goal_satisfied must remain False for modification tasks
    assert res["goal_satisfied"] is False
