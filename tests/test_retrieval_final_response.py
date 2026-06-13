"""Tests for retrieval evidence delivery in the Final Response Node.

Validates that:
1. Directory listing results appear verbatim in the final response.
2. File reading results appear verbatim in the final response.
3. Command output (e.g. python --version) appears verbatim in the final response.
4. Modification task behaviour is unchanged (metrics-only prompt, no regression).
5. Task classifier correctly distinguishes RETRIEVAL from MODIFICATION.
6. LLM failure recovery — evidence survives and a fallback response is built.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nakama_kun.ai.models.plan import Plan
from nakama_kun.ai.models.response import AIResponse
from nakama_kun.orchestration.evidence import EvidenceStore
from nakama_kun.orchestration.nodes import (
    _build_retrieval_evidence_block,
    _build_retrieval_fallback_response,
    make_final_response_node,
)
from nakama_kun.orchestration.state import AgentState
from nakama_kun.orchestration.task_classifier import (
    TASK_TYPE_MODIFICATION,
    TASK_TYPE_RETRIEVAL,
    TaskType,
    classify_task,
)
from nakama_kun.orchestration.verification import (
    CommandResult,
    VerificationReport,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_service(response_text: str = "LLM answer.") -> MagicMock:
    mock = MagicMock()
    mock.provider = MagicMock()
    llm_resp = MagicMock(spec=AIResponse)
    llm_resp.content = response_text
    mock.provider.generate = AsyncMock(return_value=llm_resp)
    return mock


def _base_state(**overrides) -> AgentState:  # type: ignore[return]
    state: AgentState = {  # type: ignore[assignment]
        "goal": "List contents of /tmp/nakama_test",
        "plan": Plan(
            goal_summary="List files",
            targets=[],
            assumptions=[],
            ordered_steps=["Run ls"],
            risks=[],
            validation_checklist=[],
        ),
        "messages": [],
        "tool_results": [],
        "verification_report": None,
        "evidence_store": None,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "reviewing",
        "task_type": TASK_TYPE_RETRIEVAL,
        "required_artifacts": [],
        "created_artifacts": [],
        "missing_artifacts": [],
        "research_budget_remaining": 15,
        "delivery_mode": False,
    }
    state.update(overrides)  # type: ignore[arg-type]
    return state


def _make_evidence_store_with_command(cmd: str, output: str, success: bool = True) -> EvidenceStore:
    store = EvidenceStore()
    store.add_command_output(cmd=cmd, exit_code=0 if success else 1, output=output, success=success)
    return store


def _make_evidence_store_with_tool(tool: str, args: dict, output: str) -> EvidenceStore:
    store = EvidenceStore()
    store.add_tool_output(tool=tool, arguments=args, success=True, output=output)
    return store


# ---------------------------------------------------------------------------
# Task classifier unit tests
# ---------------------------------------------------------------------------


class TestTaskClassifier:
    """Unit tests for classify_task() covering at least 20 examples across TaskType."""

    # --- RETRIEVAL Examples ---

    def test_list_files_is_retrieval(self) -> None:
        assert classify_task("List contents of /tmp/nakama_test") == TaskType.RETRIEVAL

    def test_ls_command_is_retrieval(self) -> None:
        assert classify_task("ls /tmp") == TaskType.RETRIEVAL

    def test_read_file_is_retrieval(self) -> None:
        assert classify_task("Read /tmp/nakama_test/README.md") == TaskType.RETRIEVAL

    def test_python_version_is_retrieval(self) -> None:
        assert classify_task("What Python version is installed?") == TaskType.RETRIEVAL

    def test_pwd_is_retrieval(self) -> None:
        assert classify_task("What is the current working directory?") == TaskType.RETRIEVAL

    def test_show_directory_is_retrieval(self) -> None:
        assert classify_task("Show me the files in this folder") == TaskType.RETRIEVAL

    def test_inspect_is_retrieval(self) -> None:
        assert classify_task("Inspect the repository structure") == TaskType.RETRIEVAL

    def test_explain_pdf_is_retrieval(self) -> None:
        assert classify_task("Explain Deepfake_Forensics.pdf") == TaskType.RETRIEVAL

    # --- CODE_MODIFICATION Examples ---

    def test_write_code_is_modification(self) -> None:
        assert classify_task("Write a Python function to sort a list") == TaskType.CODE_MODIFICATION

    def test_create_file_is_modification(self) -> None:
        assert classify_task("Create a new config file") == TaskType.CODE_MODIFICATION

    def test_refactor_is_modification(self) -> None:
        assert classify_task("Refactor the authentication module") == TaskType.CODE_MODIFICATION

    def test_implement_is_modification(self) -> None:
        assert classify_task("Implement the login feature") == TaskType.CODE_MODIFICATION

    def test_read_then_fix_prefers_modification(self) -> None:
        assert classify_task("Read the existing code and fix the bug") == TaskType.CODE_MODIFICATION

    def test_run_tests_is_modification(self) -> None:
        assert classify_task("Run tests for the project") == TaskType.CODE_MODIFICATION

    def test_fix_failing_tests_is_modification(self) -> None:
        assert classify_task("Fix failing tests") == TaskType.CODE_MODIFICATION

    def test_add_auth_is_modification(self) -> None:
        assert classify_task("Add authentication feature") == TaskType.CODE_MODIFICATION

    # --- ANALYSIS Examples ---

    def test_analyze_architecture_is_analysis(self) -> None:
        assert classify_task("Analyze repository architecture") == TaskType.ANALYSIS

    def test_analyse_codebase_is_analysis(self) -> None:
        assert classify_task("analyse codebase structure") == TaskType.ANALYSIS

    def test_design_pattern_is_analysis(self) -> None:
        assert classify_task("Identify design patterns used in nakama_kun") == TaskType.ANALYSIS

    def test_complexity_analysis_is_analysis(self) -> None:
        assert classify_task("Perform complexity analysis on state.py") == TaskType.ANALYSIS

    # --- RESEARCH Examples ---

    def test_research_api_is_research(self) -> None:
        assert classify_task("Research the ElevenLabs API details") == TaskType.RESEARCH

    def test_search_web_is_research(self) -> None:
        assert classify_task("search web for python asyncio best practices") == TaskType.RESEARCH

    def test_google_how_to_is_research(self) -> None:
        assert classify_task("Google how to build a LangGraph workflow") == TaskType.RESEARCH

    def test_benchmark_is_research(self) -> None:
        assert classify_task("Benchmark performance of SQLite vs PostgreSQL") == TaskType.RESEARCH

    # --- Default ---

    def test_unknown_defaults_to_modification(self) -> None:
        assert classify_task("Do something vague") == TaskType.CODE_MODIFICATION


# ---------------------------------------------------------------------------
# Test 1 — Directory listing: filenames appear in final response
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_directory_listing_appears_in_final_response() -> None:
    """PASS criteria: final response prompt contains each filename from ls output."""
    ls_output = "anime.mkv\nmovie.mp4\nnotes.txt\nREADME.md"
    store = _make_evidence_store_with_command(cmd="ls /tmp/nakama_test", output=ls_output)

    # Also register the ls as a tool output to exercise the tool_outputs path
    store.add_tool_output(
        tool="list_files",
        arguments={"path": "/tmp/nakama_test"},
        success=True,
        output=ls_output,
    )

    mock_service = _make_mock_service("The directory contains: anime.mkv, movie.mp4, notes.txt, README.md")
    node = make_final_response_node(mock_service)

    state = _base_state(
        goal="List contents of /tmp/nakama_test",
        task_type=TASK_TYPE_RETRIEVAL,
        evidence_store=store,
    )

    result = await node(state)

    # The LLM was given the retrieval prompt with the filenames
    called_messages = mock_service.provider.generate.call_args[0][0]
    user_msg = next(m for m in called_messages if m.role == "user")
    prompt = user_msg.content

    assert "anime.mkv" in prompt, "anime.mkv must appear in the retrieval prompt"
    assert "movie.mp4" in prompt, "movie.mp4 must appear in the retrieval prompt"
    assert "notes.txt" in prompt, "notes.txt must appear in the retrieval prompt"
    assert "README.md" in prompt, "README.md must appear in the retrieval prompt"
    assert "RETRIEVED EVIDENCE" in prompt
    assert result["status"] == "done"
    assert result["final_response"] == "The directory contains: anime.mkv, movie.mp4, notes.txt, README.md"


# ---------------------------------------------------------------------------
# Test 2 — File reading: file content appears in final response prompt
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_file_reading_content_appears_in_final_response() -> None:
    """PASS criteria: 'Hello World' is included in the prompt sent to the LLM."""
    file_content = "Hello World"
    store = EvidenceStore()
    store.add_tool_output(
        tool="read_file",
        arguments={"path": "/tmp/nakama_test/README.md"},
        success=True,
        output=file_content,
    )
    # Also add a disk validation entry (simulates verifier reading the file)
    store.add_file_validation(
        path="/tmp/nakama_test/README.md",
        exists=True,
        content=file_content,
        source="tool_read",
    )

    mock_service = _make_mock_service("The file README.md contains: Hello World")
    node = make_final_response_node(mock_service)

    state = _base_state(
        goal="Read /tmp/nakama_test/README.md",
        task_type=TASK_TYPE_RETRIEVAL,
        evidence_store=store,
    )

    result = await node(state)

    called_messages = mock_service.provider.generate.call_args[0][0]
    user_msg = next(m for m in called_messages if m.role == "user")
    prompt = user_msg.content

    assert "Hello World" in prompt, "File content must appear in the retrieval prompt"
    assert "RETRIEVED EVIDENCE" in prompt
    assert result["final_response"] == "The file README.md contains: Hello World"


# ---------------------------------------------------------------------------
# Test 3 — Python version: version string appears in final response prompt
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_python_version_appears_in_final_response() -> None:
    """PASS criteria: version string from command output is in the LLM prompt."""
    version_output = "Python 3.12.3"
    store = _make_evidence_store_with_command(
        cmd="python3 --version",
        output=version_output,
    )

    mock_service = _make_mock_service(f"The installed Python version is {version_output}.")
    node = make_final_response_node(mock_service)

    state = _base_state(
        goal="What Python version is installed?",
        task_type=TASK_TYPE_RETRIEVAL,
        evidence_store=store,
    )

    result = await node(state)

    called_messages = mock_service.provider.generate.call_args[0][0]
    user_msg = next(m for m in called_messages if m.role == "user")
    prompt = user_msg.content

    assert "Python 3.12.3" in prompt, "Version string must appear in the retrieval prompt"
    assert "RETRIEVED EVIDENCE" in prompt
    assert "Python 3.12.3" in result["final_response"]


# ---------------------------------------------------------------------------
# Test 4 — Modification task: metrics-only prompt is unchanged (regression)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_modification_task_uses_metrics_only_prompt() -> None:
    """PASS criteria: modification tasks still use the metrics-only prompt path."""
    mock_service = _make_mock_service("Implementation complete.")
    node = make_final_response_node(mock_service)

    state = _base_state(
        goal="Write a Python script to sort a list",
        task_type=TASK_TYPE_MODIFICATION,
        tool_results=[
            {
                "tool": "write_file",
                "success": True,
                "arguments": {"path": "/workspace/sort.py", "content": "pass"},
                "content": "Wrote sort.py",
            }
        ],
    )

    result = await node(state)

    called_messages = mock_service.provider.generate.call_args[0][0]
    user_msg = next(m for m in called_messages if m.role == "user")
    prompt = user_msg.content

    # Modification prompt must still contain the anti-hallucination guardrail
    assert "You MUST only cite the files created/modified" in prompt
    assert "RETRIEVED EVIDENCE" not in prompt
    assert result["final_response"] == "Implementation complete."


# ---------------------------------------------------------------------------
# Test 5 — Hybrid: task_type already in state is preserved
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_existing_task_type_in_state_is_preserved() -> None:
    """task_type already set in state must not be overridden by classify_task()."""
    # Explicitly mark a goal that looks like modification as RETRIEVAL
    mock_service = _make_mock_service("info")
    node = make_final_response_node(mock_service)

    store = EvidenceStore()
    store.add_command_output("uname -a", 0, "Linux 5.15.0", True)

    state = _base_state(
        goal="Run uname and implement something",  # contains 'implement'
        task_type=TASK_TYPE_RETRIEVAL,  # explicitly set — must win
        evidence_store=store,
    )

    await node(state)

    called_messages = mock_service.provider.generate.call_args[0][0]
    user_msg = next(m for m in called_messages if m.role == "user")
    prompt = user_msg.content

    # Should use RETRIEVAL path because state already set it
    assert "RETRIEVED EVIDENCE" in prompt


# ---------------------------------------------------------------------------
# Test 6 — LLM failure recovery
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_llm_failure_recovery_uses_evidence_fallback() -> None:
    """When LLM raises an exception the node must return a fallback built from evidence."""
    mock_service = MagicMock()
    mock_service.provider = MagicMock()
    mock_service.provider.generate = AsyncMock(side_effect=RuntimeError("Network timeout"))

    node = make_final_response_node(mock_service)

    ls_output = "anime.mkv\nmovie.mp4\nnotes.txt\nREADME.md"
    store = _make_evidence_store_with_command("ls /tmp/nakama_test", ls_output)

    state = _base_state(
        goal="List contents of /tmp/nakama_test",
        task_type=TASK_TYPE_RETRIEVAL,
        evidence_store=store,
    )

    result = await node(state)

    # Node must not raise; must return a result
    assert result["status"] == "done"
    assert result["final_response"] is not None
    assert len(result["final_response"]) > 0

    # Fallback must contain the actual retrieved data
    assert "anime.mkv" in result["final_response"]
    assert "movie.mp4" in result["final_response"]
    assert "notes.txt" in result["final_response"]
    assert "README.md" in result["final_response"]


# ---------------------------------------------------------------------------
# Test 7 — Fallback when no EvidenceStore is present (raw tool_results path)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_retrieval_without_evidence_store_uses_tool_results_fallback() -> None:
    """When EvidenceStore is absent, tool_results content is used as fallback evidence."""
    ls_output = "anime.mkv\nmovie.mp4\nnotes.txt\nREADME.md"

    mock_service = _make_mock_service("Files: anime.mkv movie.mp4 notes.txt README.md")
    node = make_final_response_node(mock_service)

    state = _base_state(
        goal="List contents of /tmp/nakama_test",
        task_type=TASK_TYPE_RETRIEVAL,
        evidence_store=None,  # No EvidenceStore
        tool_results=[
            {
                "tool": "run_command",
                "success": True,
                "arguments": {"cmd": "ls /tmp/nakama_test"},
                "content": ls_output,
            }
        ],
    )

    result = await node(state)

    called_messages = mock_service.provider.generate.call_args[0][0]
    user_msg = next(m for m in called_messages if m.role == "user")
    prompt = user_msg.content

    # The raw tool_results fallback must put the output into the prompt
    assert "anime.mkv" in prompt
    assert "RETRIEVED EVIDENCE" in prompt


# ---------------------------------------------------------------------------
# Test 8 — _build_retrieval_evidence_block unit tests
# ---------------------------------------------------------------------------


def test_build_retrieval_evidence_block_with_command_output() -> None:
    store = EvidenceStore()
    store.add_command_output("ls /tmp", 0, "file1.txt\nfile2.txt", True)

    state = _base_state(evidence_store=store)
    block = _build_retrieval_evidence_block(state)

    assert "file1.txt" in block
    assert "file2.txt" in block
    assert "ls /tmp" in block


def test_build_retrieval_evidence_block_with_read_file_tool() -> None:
    store = EvidenceStore()
    store.add_tool_output("read_file", {"path": "/tmp/a.txt"}, True, "content of a.txt")

    state = _base_state(evidence_store=store)
    block = _build_retrieval_evidence_block(state)

    assert "content of a.txt" in block
    assert "read_file" in block


def test_build_retrieval_evidence_block_excludes_write_file() -> None:
    """write_file outputs must NOT appear in the retrieval evidence block."""
    store = EvidenceStore()
    store.add_tool_output("write_file", {"path": "/tmp/x.py"}, True, "wrote successfully")

    state = _base_state(evidence_store=store)
    block = _build_retrieval_evidence_block(state)

    # write_file is not in _RETRIEVAL_TOOL_NAMES so its output must be absent
    assert "wrote successfully" not in block


def test_build_retrieval_evidence_block_empty_when_no_evidence() -> None:
    state = _base_state(evidence_store=None, tool_results=[])
    block = _build_retrieval_evidence_block(state)
    # Should be empty string
    assert block == ""


# ---------------------------------------------------------------------------
# Test 9 — _build_retrieval_fallback_response unit test
# ---------------------------------------------------------------------------


def test_build_retrieval_fallback_response_contains_evidence() -> None:
    store = EvidenceStore()
    store.add_command_output("pwd", 0, "/home/user/project", True)

    state = _base_state(
        goal="What is the current working directory?",
        evidence_store=store,
    )

    fallback = _build_retrieval_fallback_response(state["goal"], state)

    assert "/home/user/project" in fallback
    assert "What is the current working directory?" in fallback


def test_build_retrieval_fallback_response_when_no_evidence() -> None:
    state = _base_state(
        goal="List files",
        evidence_store=None,
        tool_results=[],
    )

    fallback = _build_retrieval_fallback_response(state["goal"], state)

    assert "List files" in fallback
    assert "No retrieval output was captured" in fallback
