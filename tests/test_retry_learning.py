from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nakama_kun.ai.models.message import ToolCall
from nakama_kun.ai.models.response import AIResponse
from nakama_kun.orchestration.nodes import make_executor_node, make_planner_node
from nakama_kun.orchestration.state import AgentState
from nakama_kun.tools import ToolRegistry, ToolRouter
from nakama_kun.tools.core.write_file import WriteFileTool
from nakama_kun.tools.interfaces import ToolResult


def _tool_call(name: str, arguments: dict[str, Any], call_id: str = "call-1") -> ToolCall:
    return ToolCall(id=call_id, function={"name": name, "arguments": arguments})


def _response(
    *,
    content: str | None = None,
    finish_reason: str = "stop",
    tool_calls: list[ToolCall] | None = None,
) -> MagicMock:
    response = MagicMock(spec=AIResponse)
    response.content = content
    response.finish_reason = finish_reason
    response.tool_calls = tool_calls or []
    return response


def _state() -> AgentState:
    return {
        "goal": "Fix retry learning",
        "plan": None,
        "messages": [],
        "tool_results": [],
        "verification_report": None,
        "evidence_store": None,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "executing",
    }


def _executor(chat_service: MagicMock, router: MagicMock) -> Any:
    registry = MagicMock(spec=ToolRegistry)
    registry.all_schemas.return_value = []
    return make_executor_node(chat_service, registry, router)


class _RejectingSafetyManager:
    def propose_change(self, path: str, content: str) -> Any:
        proposal = MagicMock()
        proposal.file_path = path
        proposal.content = content
        return proposal

    async def apply_proposal(self, proposal: Any, approval_provider: Any) -> bool:
        return False


@pytest.mark.anyio
async def test_rejected_file_write_returns_failure_reason() -> None:
    tool = WriteFileTool(
        safety_manager=_RejectingSafetyManager(),
        approval_provider=object(),
    )

    result = await tool.execute(path="foo.py", content="print('x')")

    assert result.success is False
    assert result.error is not None
    assert "rejected" in result.error.lower()


@pytest.mark.anyio
async def test_rejected_file_write_feedback_reaches_next_llm_prompt() -> None:
    tc = _tool_call("write_file", {"path": "foo.py", "content": "print('x')"})
    chat_service = MagicMock()
    chat_service.chat_with_tools = AsyncMock(
        side_effect=[
            _response(finish_reason="tool_calls", tool_calls=[tc]),
            _response(content="I will revise.", finish_reason="stop"),
        ]
    )
    router = MagicMock(spec=ToolRouter)
    router.dispatch = AsyncMock(
        return_value=ToolResult(success=False, error="User rejected change")
    )

    await _executor(chat_service, router)(_state())

    second_prompt = chat_service.chat_with_tools.call_args_list[1][0][0]
    prompt_text = "\n".join(m.content or "" for m in second_prompt)
    assert "User rejected change" in prompt_text
    assert "Do not repeat the same action" in prompt_text
    assert "What failed? Why did it fail? What should be changed?" in prompt_text


@pytest.mark.anyio
async def test_second_identical_failed_tool_call_is_blocked() -> None:
    args = {"path": "foo.py", "content": "print('x')"}
    tc1 = _tool_call("write_file", args, call_id="call-1")
    tc2 = _tool_call("write_file", args, call_id="call-2")
    chat_service = MagicMock()
    chat_service.chat_with_tools = AsyncMock(
        side_effect=[
            _response(finish_reason="tool_calls", tool_calls=[tc1]),
            _response(finish_reason="tool_calls", tool_calls=[tc2]),
            _response(content="I changed course.", finish_reason="stop"),
        ]
    )
    router = MagicMock(spec=ToolRouter)
    router.dispatch = AsyncMock(
        return_value=ToolResult(success=False, error="User rejected change")
    )

    result = await _executor(chat_service, router)(_state())

    router.dispatch.assert_awaited_once()
    assert len(result["tool_results"]) == 2
    assert result["tool_results"][1]["success"] is False
    assert result["tool_results"][1]["attempt_count"] == 2
    assert "Identical tool call already failed" in result["tool_results"][1]["error"]


@pytest.mark.anyio
async def test_failed_command_triggers_replanning_feedback() -> None:
    tc = _tool_call("run_command", {"cmd": "false"})
    chat_service = MagicMock()
    chat_service.chat_with_tools = AsyncMock(
        side_effect=[
            _response(finish_reason="tool_calls", tool_calls=[tc]),
            _response(content="I will inspect the command failure.", finish_reason="stop"),
        ]
    )
    router = MagicMock(spec=ToolRouter)
    router.dispatch = AsyncMock(
        return_value=ToolResult(success=False, error="Command exited with code 1")
    )

    await _executor(chat_service, router)(_state())

    second_prompt = chat_service.chat_with_tools.call_args_list[1][0][0]
    prompt_text = "\n".join(m.content or "" for m in second_prompt)
    assert "Command exited with code 1" in prompt_text
    assert "Replanning Required" in prompt_text


@pytest.mark.anyio
async def test_failed_pytest_output_guides_modify_then_rerun() -> None:
    pytest_output = (
        '{"success": false, "exit_code": 1, "stdout": "1 failed", '
        '"stderr": "AssertionError: expected 2"}'
    )
    run_fail = _tool_call("run_command", {"cmd": "pytest"}, call_id="run-1")
    write_fix = _tool_call(
        "write_file",
        {"path": "calculator.py", "content": "def add(a, b): return a + b"},
        call_id="write-1",
    )
    run_pass = _tool_call("run_command", {"cmd": "pytest -q"}, call_id="run-2")
    chat_service = MagicMock()
    chat_service.chat_with_tools = AsyncMock(
        side_effect=[
            _response(finish_reason="tool_calls", tool_calls=[run_fail]),
            _response(finish_reason="tool_calls", tool_calls=[write_fix]),
            _response(finish_reason="tool_calls", tool_calls=[run_pass]),
            _response(content="Fixed and verified.", finish_reason="stop"),
        ]
    )
    router = MagicMock(spec=ToolRouter)
    router.dispatch = AsyncMock(
        side_effect=[
            ToolResult(success=False, output=pytest_output, error=pytest_output),
            ToolResult(success=True, output="Successfully wrote file."),
            ToolResult(success=True, output='{"success": true, "exit_code": 0, "stdout": "1 passed"}'),
        ]
    )

    result = await _executor(chat_service, router)(_state())

    second_prompt = chat_service.chat_with_tools.call_args_list[1][0][0]
    prompt_text = "\n".join(m.content or "" for m in second_prompt)
    assert "AssertionError: expected 2" in prompt_text
    assert [r["tool"] for r in result["tool_results"]] == [
        "run_command",
        "write_file",
        "run_command",
    ]


@pytest.mark.anyio
async def test_identical_failed_calls_stop_at_executor_round_limit() -> None:
    tc = _tool_call("write_file", {"path": "foo.py", "content": "same"})
    chat_service = MagicMock()
    chat_service.chat_with_tools = AsyncMock(
        side_effect=[_response(finish_reason="tool_calls", tool_calls=[tc]) for _ in range(10)]
    )
    router = MagicMock(spec=ToolRouter)
    router.dispatch = AsyncMock(
        return_value=ToolResult(success=False, error="User rejected change")
    )

    result = await _executor(chat_service, router)(_state())

    assert len(result["tool_results"]) == 10
    assert max(r["attempt_count"] for r in result["tool_results"]) <= 10
    assert chat_service.chat_with_tools.call_count == 10
    router.dispatch.assert_awaited_once()


@pytest.mark.anyio
async def test_planner_prompt_contains_user_rejection_awareness() -> None:
    planner_service = MagicMock()
    planner_service.plan = AsyncMock(return_value=(None, "raw plan"))
    planner_node = make_planner_node(planner_service)
    state = _state()
    state["reviewer_feedback"] = "[REJECTED] Try again."
    state["tool_results"] = [
        {
            "tool": "write_file",
            "arguments": {"path": "foo.py", "content": "old"},
            "success": False,
            "content": "Tool: write_file\nStatus: FAILED",
            "error": "User rejected change",
            "attempt_count": 1,
        }
    ]

    await planner_node(state)

    prompt = planner_service.plan.call_args.args[0]
    assert "User rejected change" in prompt
    assert "Do not resubmit identical content" in prompt
