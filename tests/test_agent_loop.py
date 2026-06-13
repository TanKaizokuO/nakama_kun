"""
tests/test_agent_loop.py — Unit tests for the Agent Mode agentic execution loop.

All tests mock the ChatService so no real network calls are made.

Covers:
  - Loop terminates on first-round "stop" (no tool calls).
  - Loop executes tool calls and appends role="tool" messages in subsequent rounds.
  - Loop stops at iteration limit and requests a final answer.
  - Tool results are correctly appended as role="tool" messages.
  - Unknown tool name returns an error result (not an unhandled exception).
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nakama_kun.ai.models.message import Message, ToolCall
from nakama_kun.ai.models.response import AIResponse, TokenUsage
from nakama_kun.tools import ToolRegistry, build_default_registry
from nakama_kun.tools.interfaces import BaseTool, ToolResult

# ---------------------------------------------------------------------------
# Helpers
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


def _make_tool_call(name: str, arguments: dict[str, Any], call_id: str = "call_1") -> ToolCall:
    return ToolCall(
        id=call_id,
        type="function",
        function={"name": name, "arguments": arguments},
    )


class _EchoTool(BaseTool):
    """A deterministic test tool that echoes its 'msg' argument."""

    name = "echo"
    description = "Echo a message."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {"msg": {"type": "string"}},
        "required": ["msg"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, output=f"echo: {kwargs.get('msg', '')}")


def _build_agent_mode(chat_service: Any, registry: ToolRegistry | None = None) -> Any:
    """Import and instantiate AgentMode without triggering asyncio.run."""
    from nakama_kun.modes.agent_mode import AgentMode

    if registry is None:
        registry = ToolRegistry()
        registry.register(_EchoTool())

    return AgentMode(chat_service=chat_service, tool_registry=registry)


# ---------------------------------------------------------------------------
# _agent_loop tests (call the async method directly)
# ---------------------------------------------------------------------------


class TestAgentLoop:
    """Tests for AgentMode._agent_loop()."""

    def _make_chat_service(self, responses: list[AIResponse]) -> Any:
        """Build a mock ChatService that yields responses in order."""
        chat_service = MagicMock()
        chat_service.provider = MagicMock()
        chat_service.provider.settings = MagicMock()
        chat_service.provider.settings.openrouter_model = "test-model"
        chat_service.chat_with_tools = AsyncMock(side_effect=responses)

        mock_plan_text = """Goal: Test task
        Target Files/Modules: []
        Assumptions: []
        Execution Steps:
        1. Step 1
        Risks & Hazards: []
        Validation Checklist: []
        """

        async def mock_generate(messages: list[Message], **kwargs: Any) -> AIResponse:
            sys_msgs = [m for m in messages if m.role == "system"]
            content_lower = "".join(m.content or "" for m in sys_msgs).lower()
            user_msgs = [m for m in messages if m.role == "user"]
            prompt_lower = "".join(m.content or "" for m in user_msgs).lower()

            if "reviewer" in content_lower or "reviewer" in prompt_lower:
                return _make_ai_response(content="[APPROVED] All tasks met.")
            elif "synthesize" in prompt_lower or "synthesize" in content_lower:
                final_content = "Direct answer."
                if responses:
                    for r in reversed(responses):
                        if r.content:
                            final_content = r.content
                            break
                return _make_ai_response(content=final_content)
            else:
                return _make_ai_response(content=mock_plan_text)

        chat_service.provider.generate = AsyncMock(side_effect=mock_generate)
        return chat_service

    def test_single_round_stop(self) -> None:
        """Model answers immediately with finish_reason='stop' — loop runs once."""
        responses = [_make_ai_response(content="Direct answer.", finish_reason="stop")]
        chat_service = self._make_chat_service(responses)
        agent = _build_agent_mode(chat_service)

        history: list[Message] = []
        result = asyncio.run(
            agent._agent_loop("Perform a task", history, [])
        )

        assert result == "Direct answer."
        chat_service.chat_with_tools.assert_called_once()

    def test_tool_call_then_stop(self) -> None:
        """Model calls a tool in round 1, then gives final answer in round 2."""
        tc = _make_tool_call("echo", {"msg": "hello"})
        responses = [
            _make_ai_response(finish_reason="tool_calls", tool_calls=[tc]),
            _make_ai_response(content="Final answer after tool.", finish_reason="stop"),
        ]
        chat_service = self._make_chat_service(responses)
        agent = _build_agent_mode(chat_service)

        history: list[Message] = []
        result = asyncio.run(
            agent._agent_loop("Use the echo tool", history, [])
        )

        assert result == "Final answer after tool."
        assert chat_service.chat_with_tools.call_count == 2

        # The second call should include a role="tool" message in its messages arg
        second_call_messages: list[Message] = chat_service.chat_with_tools.call_args_list[1][0][0]
        tool_messages = [m for m in second_call_messages if m.role == "tool"]
        assert len(tool_messages) == 1
        assert "echo: hello" in (tool_messages[0].content or "")

    def test_multiple_tool_calls_in_one_round(self) -> None:
        """Model requests two tool calls in the same round."""
        tc1 = _make_tool_call("echo", {"msg": "a"}, call_id="c1")
        tc2 = _make_tool_call("echo", {"msg": "b"}, call_id="c2")
        responses = [
            _make_ai_response(finish_reason="tool_calls", tool_calls=[tc1, tc2]),
            _make_ai_response(content="Got both.", finish_reason="stop"),
        ]
        chat_service = self._make_chat_service(responses)
        agent = _build_agent_mode(chat_service)

        history: list[Message] = []
        result = asyncio.run(
            agent._agent_loop("Use both", history, [])
        )

        assert result == "Got both."
        second_call_messages: list[Message] = chat_service.chat_with_tools.call_args_list[1][0][0]
        tool_messages = [m for m in second_call_messages if m.role == "tool"]
        assert len(tool_messages) == 2

    def test_iteration_limit(self) -> None:
        """Loop should stop after _MAX_ITERATIONS rounds and request a final answer."""
        from nakama_kun.modes import agent_mode as agent_module

        max_iter = agent_module._MAX_ITERATIONS
        tc = _make_tool_call("echo", {"msg": "loop"})

        # Return tool_calls for every round within the limit, plus one more for the forced stop request
        responses = [
            _make_ai_response(finish_reason="tool_calls", tool_calls=[tc])
            for _ in range(max_iter)
        ] + [_make_ai_response(content="Final forced answer.", finish_reason="stop")]

        chat_service = self._make_chat_service(responses)
        agent = _build_agent_mode(chat_service)

        history: list[Message] = []
        result = asyncio.run(
            agent._agent_loop("Loop forever", history, [])
        )

        assert result == "Final forced answer."
        # max_iter tool-call rounds
        assert chat_service.chat_with_tools.call_count == max_iter

    def test_history_gets_user_message_appended(self) -> None:
        """_agent_loop appends the user message to the shared history list."""
        responses = [_make_ai_response(content="ok", finish_reason="stop")]
        chat_service = self._make_chat_service(responses)
        agent = _build_agent_mode(chat_service)

        history: list[Message] = []
        asyncio.run(agent._agent_loop("My task", history, []))

        assert any(m.role == "user" and m.content == "My task" for m in history)

    def test_unknown_tool_does_not_crash_loop(self) -> None:
        """If the LLM calls an unknown tool, the loop continues with an error message."""
        tc = _make_tool_call("no_such_tool", {})
        responses = [
            _make_ai_response(finish_reason="tool_calls", tool_calls=[tc]),
            _make_ai_response(content="Handled the error.", finish_reason="stop"),
        ]
        chat_service = self._make_chat_service(responses)
        # Use an empty registry — no tools registered
        agent = _build_agent_mode(chat_service, registry=ToolRegistry())

        history: list[Message] = []
        result = asyncio.run(
            agent._agent_loop("Call unknown", history, [])
        )

        # Should not raise; should propagate an error message to the LLM and finish
        assert result == "Handled the error."


# ---------------------------------------------------------------------------
# _execute_tool_call tests
# ---------------------------------------------------------------------------


class TestExecuteToolCall:
    def _make_agent(self) -> Any:
        chat_service = MagicMock()
        chat_service.provider = MagicMock()
        chat_service.provider.settings = MagicMock()
        chat_service.provider.settings.openrouter_model = "test-model"
        registry = ToolRegistry()
        registry.register(_EchoTool())
        return _build_agent_mode(chat_service, registry=registry)

    @pytest.mark.anyio
    async def test_successful_dispatch(self) -> None:
        agent = self._make_agent()
        tc = _make_tool_call("echo", {"msg": "nakama"})
        content = await agent._execute_tool_call(tc)
        assert "echo: nakama" in content

    @pytest.mark.anyio
    async def test_unknown_tool_returns_error_string(self) -> None:
        agent = self._make_agent()
        tc = _make_tool_call("ghost_tool", {})
        content = await agent._execute_tool_call(tc)
        assert "ERROR" in content

    def test_tool_result_content_success(self) -> None:
        result = ToolResult(success=True, output="good output")
        assert result.to_content() == "good output"

    def test_tool_result_content_failure(self) -> None:
        result = ToolResult(success=False, error="bad thing happened")
        assert "ERROR" in result.to_content()
        assert "bad thing happened" in result.to_content()


# ---------------------------------------------------------------------------
# build_default_registry
# ---------------------------------------------------------------------------


class TestBuildDefaultRegistry:
    def test_has_six_tools(self, tmp_path: object) -> None:
        registry = build_default_registry(str(tmp_path))
        assert len(registry) == 6

    def test_tool_names(self, tmp_path: object) -> None:
        registry = build_default_registry(str(tmp_path))
        assert set(registry.names()) == {
            "read_file",
            "write_file",
            "list_files",
            "search_files",
            "search_vector_store",
            "run_command",
        }

    def test_all_schemas_well_formed(self, tmp_path: object) -> None:
        registry = build_default_registry(str(tmp_path))
        for schema in registry.all_schemas():
            assert schema["type"] == "function"
            assert "name" in schema["function"]
            assert "description" in schema["function"]
            assert "parameters" in schema["function"]
