from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from nakama_kun.ai.models.message import Message, ToolCall
from nakama_kun.ai.models.response import AIResponse, TokenUsage
from nakama_kun.ai.models.plan import Plan
from nakama_kun.orchestration.state import AgentState
from nakama_kun.orchestration.task_classifier import TASK_TYPE_RETRIEVAL
from nakama_kun.orchestration.workflow import route_after_executor, route_after_review
from nakama_kun.orchestration.nodes import make_executor_node, make_final_response_node, make_reviewer_node
from nakama_kun.tools import ToolRegistry, ToolRouter, ToolResult
from nakama_kun.tools.interfaces import BaseTool


# ---------------------------------------------------------------------------
# Test Mocks and Helpers
# ---------------------------------------------------------------------------

def _make_ai_response(content: str | None = None, finish_reason: str = "stop", tool_calls: list[ToolCall] | None = None) -> AIResponse:
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


class MockListFilesTool(BaseTool):
    name = "list_files"
    description = "List files in a directory."
    parameters = {"type": "object", "properties": {"path": {"type": "string"}}, "required": []}

    async def execute(self, **kwargs) -> ToolResult:
        path = kwargs.get("path", "")
        if "missing" in path or "ghost" in path:
            return ToolResult(success=False, error="Directory does not exist")
        return ToolResult(success=True, output="index.js\npackage.json\nREADME.md")


class MockReadFileTool(BaseTool):
    name = "read_file"
    description = "Read a file."
    parameters = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}

    async def execute(self, **kwargs) -> ToolResult:
        path = kwargs.get("path", "")
        if "missing" in path or "ghost" in path:
            return ToolResult(success=False, error="File does not exist")
        return ToolResult(success=True, output="content of the read file")


class MockSearchVectorStoreTool(BaseTool):
    name = "search_vector_store"
    description = "Search vector store."
    parameters = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}

    async def execute(self, **kwargs) -> ToolResult:
        query = kwargs.get("query", "")
        if "missing" in query or "nonexistent" in query:
            return ToolResult(success=False, error="No documents found")
        return ToolResult(success=True, output="extracted text summary from the PDF report")


class MockRunCommandTool(BaseTool):
    name = "run_command"
    description = "Run command."
    parameters = {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}

    async def execute(self, **kwargs) -> ToolResult:
        cmd = kwargs.get("cmd", "")
        if "--version" in cmd:
            return ToolResult(success=True, output="v14.17.0")
        if "ls" in cmd:
            return ToolResult(success=True, output="main.py\nutils.py")
        return ToolResult(success=True, output="generic output")


class MockWriteFileTool(BaseTool):
    name = "write_file"
    description = "Write a file."
    parameters = {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, output="wrote file successfully")


def _get_base_state(goal: str) -> AgentState:
    state: AgentState = {
        "goal": goal,
        "plan": Plan(
            goal_summary=goal,
            targets=[],
            assumptions=[],
            ordered_steps=["Step 1"],
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
        "status": "planning",
        "task_type": TASK_TYPE_RETRIEVAL,
        "required_artifacts": [],
        "created_artifacts": [],
        "missing_artifacts": [],
        "research_budget_remaining": 15,
        "delivery_mode": False,
        "goal_satisfied": False,
        "early_stop_telemetry": None,
        "agent_history": [],
    }
    return state


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_regression_directory_listing() -> None:
    # Scenario 1: Directory Listing
    tc = _make_tool_call("list_files", {"path": "/workspace"})
    chat_service = MagicMock()
    chat_service.chat_with_tools = AsyncMock(return_value=_make_ai_response(finish_reason="tool_calls", tool_calls=[tc]))

    registry = ToolRegistry()
    registry.register(MockListFilesTool())
    registry.register(MockWriteFileTool())
    router = ToolRouter(registry)

    # 1. Execute Node
    executor_node = make_executor_node(chat_service, registry, router)
    state = _get_base_state("List files in the workspace directory")
    res_exec = await executor_node(state)

    # ASSERTIONS:
    # - Early termination occurred, only 1 tool call executed
    assert len(res_exec["tool_results"]) == 1
    assert res_exec["goal_satisfied"] is True
    # - No mutations allowed
    write_calls = [r for r in res_exec["tool_results"] if r["tool"] == "write_file"]
    assert len(write_calls) == 0

    # Merge execution node updates back into state for downstream nodes
    state.update(res_exec)

    # 2. Workflow Routing
    # - No retries after success (route goes straight to final_response)
    assert route_after_executor(state) == "final_response"
    assert route_after_review(state) == "final_response"

    # 3. Final Response Node
    # - Grounded response contains evidence
    mock_llm_service = MagicMock()
    mock_llm_service.provider = MagicMock()
    mock_llm_service.provider.generate = AsyncMock(return_value=_make_ai_response("Here is the directory listing: README.md, package.json"))
    final_node = make_final_response_node(mock_llm_service)
    res_final = await final_node(state)

    assert "README.md" in res_final["final_response"]


@pytest.mark.anyio
async def test_regression_file_reading() -> None:
    # Scenario 2: File Reading
    tc = _make_tool_call("read_file", {"path": "config.json"})
    chat_service = MagicMock()
    chat_service.chat_with_tools = AsyncMock(return_value=_make_ai_response(finish_reason="tool_calls", tool_calls=[tc]))

    registry = ToolRegistry()
    registry.register(MockReadFileTool())
    router = ToolRouter(registry)

    executor_node = make_executor_node(chat_service, registry, router)
    state = _get_base_state("Read config.json file")
    res_exec = await executor_node(state)

    assert len(res_exec["tool_results"]) == 1
    assert res_exec["goal_satisfied"] is True
    state.update(res_exec)
    assert route_after_executor(state) == "final_response"
    assert route_after_review(state) == "final_response"


@pytest.mark.anyio
async def test_regression_pdf_explanation() -> None:
    # Scenario 3: PDF Explanation
    tc = _make_tool_call("search_vector_store", {"query": "deepfake models"})
    chat_service = MagicMock()
    chat_service.chat_with_tools = AsyncMock(return_value=_make_ai_response(finish_reason="tool_calls", tool_calls=[tc]))

    registry = ToolRegistry()
    registry.register(MockSearchVectorStoreTool())
    router = ToolRouter(registry)

    executor_node = make_executor_node(chat_service, registry, router)
    state = _get_base_state("Explain PDF project_report.pdf")
    res_exec = await executor_node(state)

    assert len(res_exec["tool_results"]) == 1
    assert res_exec["goal_satisfied"] is True
    state.update(res_exec)
    assert route_after_executor(state) == "final_response"
    assert route_after_review(state) == "final_response"


@pytest.mark.anyio
async def test_regression_version_query() -> None:
    # Scenario 4: Version Query
    tc = _make_tool_call("run_command", {"cmd": "node --version"})
    chat_service = MagicMock()
    chat_service.chat_with_tools = AsyncMock(return_value=_make_ai_response(finish_reason="tool_calls", tool_calls=[tc]))

    registry = ToolRegistry()
    registry.register(MockRunCommandTool())
    router = ToolRouter(registry)

    executor_node = make_executor_node(chat_service, registry, router)
    state = _get_base_state("Check node version")
    res_exec = await executor_node(state)

    assert len(res_exec["tool_results"]) == 1
    assert res_exec["goal_satisfied"] is True
    state.update(res_exec)
    assert route_after_executor(state) == "final_response"
    assert route_after_review(state) == "final_response"


@pytest.mark.anyio
async def test_regression_missing_file() -> None:
    # Scenario 5: Missing File
    tc = _make_tool_call("read_file", {"path": "ghost.json"})
    chat_service = MagicMock()
    chat_service.chat_with_tools = AsyncMock(return_value=_make_ai_response(finish_reason="tool_calls", tool_calls=[tc]))

    registry = ToolRegistry()
    registry.register(MockReadFileTool())
    router = ToolRouter(registry)

    executor_node = make_executor_node(chat_service, registry, router)
    state = _get_base_state("Read ghost.json file")
    res_exec = await executor_node(state)

    # ASSERTIONS:
    # - Retrieval fails (success = False)
    assert res_exec["tool_results"][0]["success"] is False
    assert res_exec["goal_satisfied"] is False
    state.update(res_exec)
    # - Normal routing path followed when goal unsatisfied
    assert route_after_executor(state) == "verifier"


@pytest.mark.anyio
async def test_regression_missing_directory() -> None:
    # Scenario 6: Missing Directory
    tc = _make_tool_call("list_files", {"path": "missing_folder"})
    chat_service = MagicMock()
    chat_service.chat_with_tools = AsyncMock(return_value=_make_ai_response(finish_reason="tool_calls", tool_calls=[tc]))

    registry = ToolRegistry()
    registry.register(MockListFilesTool())
    router = ToolRouter(registry)

    executor_node = make_executor_node(chat_service, registry, router)
    state = _get_base_state("List files in missing_folder")
    res_exec = await executor_node(state)

    assert res_exec["tool_results"][0]["success"] is False
    assert res_exec["goal_satisfied"] is False
    state.update(res_exec)
    assert route_after_executor(state) == "verifier"


@pytest.mark.anyio
async def test_regression_missing_pdf() -> None:
    # Scenario 7: Missing PDF
    tc = _make_tool_call("search_vector_store", {"query": "nonexistent_report"})
    chat_service = MagicMock()
    chat_service.chat_with_tools = AsyncMock(return_value=_make_ai_response(finish_reason="tool_calls", tool_calls=[tc]))

    registry = ToolRegistry()
    registry.register(MockSearchVectorStoreTool())
    router = ToolRouter(registry)

    executor_node = make_executor_node(chat_service, registry, router)
    state = _get_base_state("Explain nonexistent_report.pdf")
    res_exec = await executor_node(state)

    assert res_exec["tool_results"][0]["success"] is False
    assert res_exec["goal_satisfied"] is False
    state.update(res_exec)
    assert route_after_executor(state) == "verifier"
