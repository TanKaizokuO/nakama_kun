import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from nakama_kun.ai.models.message import Message, ToolCall
from nakama_kun.ai.models.response import AIResponse, TokenUsage
from nakama_kun.orchestration.state import AgentState
from nakama_kun.orchestration.task_classifier import TASK_TYPE_RETRIEVAL
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


class DummyRetrievalTool(BaseTool):
    name = "run_command"
    description = "Run a shell command."
    parameters = {
        "type": "object",
        "properties": {"cmd": {"type": "string"}},
        "required": ["cmd"],
    }

    async def execute(self, **kwargs) -> ToolResult:
        cmd = kwargs.get("cmd", "")
        if "--version" in cmd:
            return ToolResult(success=True, output="Python 3.12.3")
        return ToolResult(success=True, output="dummy command output")


class DummyReadFileTool(BaseTool):
    name = "read_file"
    description = "Read a file."
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, output="dummy file contents")


class DummyWriteFileTool(BaseTool):
    name = "write_file"
    description = "Write a file."
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    }

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, output="wrote file")


@pytest.mark.anyio
async def test_list_directory_early_termination() -> None:
    # Task: List contents of /tmp/test_dir
    tc = _make_tool_call("run_command", {"cmd": "ls /tmp/test_dir"})
    # Chat service returns a tool call, and then if it loops, we'd return stop, but we expect it to terminate early after 1 call
    responses = [
        _make_ai_response(finish_reason="tool_calls", tool_calls=[tc]),
        _make_ai_response(content="Final response containing dir contents", finish_reason="stop")
    ]
    chat_service = MagicMock()
    chat_service.chat_with_tools = AsyncMock(side_effect=responses)

    registry = ToolRegistry()
    registry.register(DummyRetrievalTool())
    registry.register(DummyWriteFileTool())
    router = ToolRouter(registry)

    agent = ExecutorAgent(chat_service, registry, router)
    state = {
        "goal": "List contents of /tmp/test_dir",
        "task_type": TASK_TYPE_RETRIEVAL,
        "messages": [],
        "tool_results": [],
        "created_artifacts": [],
        "research_budget_remaining": 15,
        "delivery_mode": False,
        "goal_satisfied": False,
    }

    res = await agent.run(state)

    # Assertions:
    # 1. Exactly 1 tool call dispatched (which is run_command).
    assert len(res["tool_results"]) == 1
    assert res["tool_results"][0]["tool"] == "run_command"
    assert res["tool_results"][0]["success"] is True
    # 2. goal_satisfied is set to True
    assert res["goal_satisfied"] is True
    # 3. No write_file calls executed
    write_calls = [r for r in res["tool_results"] if r["tool"] == "write_file"]
    assert len(write_calls) == 0


@pytest.mark.anyio
async def test_read_file_early_termination() -> None:
    # Task: Read README.md
    tc = _make_tool_call("read_file", {"path": "README.md"})
    responses = [
        _make_ai_response(finish_reason="tool_calls", tool_calls=[tc]),
        _make_ai_response(content="Final response containing README.md content", finish_reason="stop")
    ]
    chat_service = MagicMock()
    chat_service.chat_with_tools = AsyncMock(side_effect=responses)

    registry = ToolRegistry()
    registry.register(DummyReadFileTool())
    registry.register(DummyWriteFileTool())
    router = ToolRouter(registry)

    agent = ExecutorAgent(chat_service, registry, router)
    state = {
        "goal": "Read README.md",
        "task_type": TASK_TYPE_RETRIEVAL,
        "messages": [],
        "tool_results": [],
        "created_artifacts": [],
        "research_budget_remaining": 15,
        "delivery_mode": False,
        "goal_satisfied": False,
    }

    res = await agent.run(state)

    assert len(res["tool_results"]) == 1
    assert res["tool_results"][0]["tool"] == "read_file"
    assert res["goal_satisfied"] is True
    write_calls = [r for r in res["tool_results"] if r["tool"] == "write_file"]
    assert len(write_calls) == 0


@pytest.mark.anyio
async def test_python_version_early_termination() -> None:
    # Task: What Python version is installed?
    tc = _make_tool_call("run_command", {"cmd": "python --version"})
    responses = [
        _make_ai_response(finish_reason="tool_calls", tool_calls=[tc]),
        _make_ai_response(content="Python 3.12", finish_reason="stop")
    ]
    chat_service = MagicMock()
    chat_service.chat_with_tools = AsyncMock(side_effect=responses)

    registry = ToolRegistry()
    registry.register(DummyRetrievalTool())
    registry.register(DummyWriteFileTool())
    router = ToolRouter(registry)

    agent = ExecutorAgent(chat_service, registry, router)
    state = {
        "goal": "What Python version is installed?",
        "task_type": TASK_TYPE_RETRIEVAL,
        "messages": [],
        "tool_results": [],
        "created_artifacts": [],
        "research_budget_remaining": 15,
        "delivery_mode": False,
        "goal_satisfied": False,
    }

    res = await agent.run(state)

    assert len(res["tool_results"]) == 1
    assert res["tool_results"][0]["tool"] == "run_command"
    assert res["goal_satisfied"] is True
    write_calls = [r for r in res["tool_results"] if r["tool"] == "write_file"]
    assert len(write_calls) == 0


@pytest.mark.anyio
async def test_retrieval_blocks_mutation() -> None:
    # If the LLM tries to call write_file in a retrieval task, it must be blocked!
    tc = _make_tool_call("write_file", {"path": "test_output.txt", "content": "hello"})
    responses = [
        _make_ai_response(finish_reason="tool_calls", tool_calls=[tc]),
        _make_ai_response(content="Blocked write", finish_reason="stop")
    ]
    chat_service = MagicMock()
    chat_service.chat_with_tools = AsyncMock(side_effect=responses)

    registry = ToolRegistry()
    registry.register(DummyWriteFileTool())
    router = ToolRouter(registry)

    agent = ExecutorAgent(chat_service, registry, router)
    state = {
        "goal": "Retrieve list and try writing",
        "task_type": TASK_TYPE_RETRIEVAL,
        "messages": [],
        "tool_results": [],
        "created_artifacts": [],
        "research_budget_remaining": 15,
        "delivery_mode": False,
        "goal_satisfied": False,
    }

    res = await agent.run(state)

    # The write_file call must have failed/been blocked
    assert len(res["tool_results"]) == 1
    assert res["tool_results"][0]["tool"] == "write_file"
    assert res["tool_results"][0]["success"] is False
    assert "Blocked" in res["tool_results"][0]["content"]
    assert res["goal_satisfied"] is False
