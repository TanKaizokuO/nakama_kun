from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from nakama_kun.ai.models.message import Message, ToolCall
from nakama_kun.ai.models.response import AIResponse, TokenUsage
from nakama_kun.orchestration.state import AgentState
from nakama_kun.orchestration.task_classifier import TASK_TYPE_RETRIEVAL
from nakama_kun.orchestration.workflow import route_after_executor
from nakama_kun.agents.executor import ExecutorAgent
from nakama_kun.tools import ToolRegistry, ToolResult, ToolRouter
from nakama_kun.tools.interfaces import BaseTool


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


class DummyListingTool(BaseTool):
    name = "list_files"
    description = "List files in a directory."
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": [],
    }

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, output="file1.txt\nfile2.txt")


class DummyPDFTool(BaseTool):
    name = "search_vector_store"
    description = "Search vector store."
    parameters = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, output="extracted text from PDF document")


class DummyRunCommandTool(BaseTool):
    name = "run_command"
    description = "Run command."
    parameters = {
        "type": "object",
        "properties": {"cmd": {"type": "string"}},
        "required": ["cmd"],
    }

    async def execute(self, **kwargs) -> ToolResult:
        cmd = kwargs.get("cmd", "")
        if "ls" in cmd:
            return ToolResult(success=True, output="dir_content_a\ndir_content_b")
        if "pdftotext" in cmd:
            return ToolResult(success=True, output="parsed pdf text content")
        return ToolResult(success=True, output="generic output")


def test_route_after_executor() -> None:
    # 1. Goal satisfied -> Route to final_response
    state_satisfied: AgentState = {"goal_satisfied": True}
    assert route_after_executor(state_satisfied) == "final_response"

    # 2. Goal NOT satisfied -> Route to verifier
    state_not_satisfied: AgentState = {"goal_satisfied": False}
    assert route_after_executor(state_not_satisfied) == "verifier"


@pytest.mark.anyio
async def test_directory_listing_early_termination() -> None:
    # Task: List contents of /home/user/project
    # LLM issues run_command to list files
    tc = _make_tool_call("run_command", {"cmd": "ls /home/user/project"})
    
    # We should stop immediately after this tool runs and not call the next stop message response
    chat_service = MagicMock()
    chat_service.chat_with_tools = AsyncMock(return_value=_make_ai_response(finish_reason="tool_calls", tool_calls=[tc]))

    registry = ToolRegistry()
    registry.register(DummyRunCommandTool())
    router = ToolRouter(registry)

    agent = ExecutorAgent(chat_service, registry, router)
    state = {
        "goal": "List contents of /home/user/project",
        "task_type": TASK_TYPE_RETRIEVAL,
        "messages": [],
        "tool_results": [],
        "created_artifacts": [],
        "research_budget_remaining": 15,
        "delivery_mode": False,
        "goal_satisfied": False,
    }

    res = await agent.run(state)

    # Assertions
    # 1. Terminated early with exactly 1 tool call
    assert len(res["tool_results"]) == 1
    assert res["tool_results"][0]["tool"] == "run_command"
    assert res["tool_results"][0]["success"] is True

    # 2. Goal satisfied is True
    assert res["goal_satisfied"] is True

    # 3. Telemetry recorded
    telemetry = res.get("early_stop_telemetry")
    assert telemetry is not None
    assert telemetry["stop_round"] == 1
    assert "Directory listing obtained via command" in telemetry["stop_reason"]
    assert telemetry["evidence_used"]["tool"] == "run_command"


@pytest.mark.anyio
async def test_pdf_explanation_early_termination() -> None:
    # Task: Explain content of project_report.pdf
    # LLM issues search_vector_store tool
    tc = _make_tool_call("search_vector_store", {"query": "project status"})
    
    chat_service = MagicMock()
    chat_service.chat_with_tools = AsyncMock(return_value=_make_ai_response(finish_reason="tool_calls", tool_calls=[tc]))

    registry = ToolRegistry()
    registry.register(DummyPDFTool())
    router = ToolRouter(registry)

    agent = ExecutorAgent(chat_service, registry, router)
    state = {
        "goal": "Explain content of project_report.pdf",
        "task_type": TASK_TYPE_RETRIEVAL,
        "messages": [],
        "tool_results": [],
        "created_artifacts": [],
        "research_budget_remaining": 15,
        "delivery_mode": False,
        "goal_satisfied": False,
    }

    res = await agent.run(state)

    # Assertions
    # 1. Terminated early with exactly 1 tool call
    assert len(res["tool_results"]) == 1
    assert res["tool_results"][0]["tool"] == "search_vector_store"

    # 2. Goal satisfied is True
    assert res["goal_satisfied"] is True

    # 3. Telemetry recorded
    telemetry = res.get("early_stop_telemetry")
    assert telemetry is not None
    assert telemetry["stop_round"] == 1
    assert "PDF text retrieved via tool" in telemetry["stop_reason"]
    assert telemetry["evidence_used"]["tool"] == "search_vector_store"
