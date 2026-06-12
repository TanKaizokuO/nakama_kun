"""
tests/test_required_artifacts.py — Comprehensive tests for the required-artifact
enforcement pipeline introduced in Delivery Mode.

Covers:
  1. Verifier correctly rejects when required artifacts are missing.
  2. Verifier approves when required artifacts are present on disk.
  3. Delivery mode blocks exploration tools immediately.
  4. Delivery mode guidance message is injected when artifacts are missing.
  5. Budget exhaustion (research threshold reached) triggers delivery mode.
  6. Retry memory accumulates and deduplicates completed/failed actions.
  7. Retry memory tracks failed attempt signatures.
  8. Planner retry prompt includes retry memory and missing artifact failures.
  9. Reviewer deterministic gate rejects when missing_artifacts is non-empty.
 10. Tool router returns structured error on malformed JSON arguments.
 11. Tool router returns structured error on missing required schema argument.
 12. Duplicate tool call failure is blocked with retry-memory signature check.
 13. Delivery guidance message format is correct.
 14. _paths_match handles basename-only matching.
 15. _missing_required_artifacts correctly cross-references created list.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nakama_kun.ai.models.message import Message, ToolCall
from nakama_kun.ai.models.plan import Plan
from nakama_kun.ai.models.response import AIResponse, TokenUsage
from nakama_kun.orchestration.nodes import (
    EXPLORATION_TOOLS,
    RESEARCH_THRESHOLD,
    _action_signature,
    _build_retry_memory,
    _delivery_guidance,
    _empty_retry_memory,
    _missing_required_artifacts,
    _normalize_tool_arguments,
    _paths_match,
    _prioritize_tool_schemas,
    make_executor_node,
    make_reviewer_node,
    make_verifier_node,
    make_planner_node,
)
from nakama_kun.orchestration.state import AgentState
from nakama_kun.tools.interfaces import ToolResult
from nakama_kun.tools.registry import ToolRegistry
from nakama_kun.tools.router import ToolRouter


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
        usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        finish_reason=finish_reason,
        latency=0.0,
        tool_calls=tool_calls,
    )


def _make_tool_call(name: str, arguments: Any, call_id: str = "call_1") -> ToolCall:
    return ToolCall(
        id=call_id,
        type="function",
        function={"name": name, "arguments": arguments},
    )


def _base_state(**overrides: Any) -> AgentState:
    state: AgentState = {
        "goal": "Analyze repo and create ARCHITECTURE.md",
        "plan": Plan(
            goal_summary="Create ARCHITECTURE.md",
            ordered_steps=["Explore", "Write"],
            required_artifacts=["ARCHITECTURE.md"],
        ),
        "required_artifacts": ["ARCHITECTURE.md"],
        "created_artifacts": [],
        "missing_artifacts": ["ARCHITECTURE.md"],
        "research_budget_remaining": RESEARCH_THRESHOLD,
        "delivery_mode": False,
        "retry_memory": _empty_retry_memory(),
        "messages": [],
        "tool_results": [],
        "verification_report": None,
        "evidence_store": None,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "executing",
    }
    state.update(overrides)
    return state


class _MockChatService:
    """Lightweight mock that yields pre-built AIResponse objects in order."""

    def __init__(self, responses: list[AIResponse]) -> None:
        self.responses = responses
        self._idx = 0

    async def chat_with_tools(
        self, messages: list[Message], schemas: list[dict[str, Any]]
    ) -> AIResponse:
        if self._idx < len(self.responses):
            resp = self.responses[self._idx]
            self._idx += 1
            return resp
        return _make_ai_response(content="Done.", finish_reason="stop")


# ---------------------------------------------------------------------------
# 1–2: Verifier required-artifact gate
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_verifier_rejects_when_required_artifact_missing(tmp_path: Any) -> None:
    """Verifier must emit REJECT when a required artifact is absent from workspace."""
    verifier_node = make_verifier_node(workspace_root=str(tmp_path))
    result = await verifier_node(_base_state())
    report = result["verification_report"]
    signal = report.evaluate_outcome()

    assert signal.recommendation == "REJECT"
    assert "required artifact" in signal.reason.lower()
    assert "ARCHITECTURE.md" in signal.reason


@pytest.mark.anyio
async def test_verifier_approves_when_required_artifact_exists(tmp_path: Any) -> None:
    """Verifier must emit APPROVE when required artifact exists on disk."""
    (tmp_path / "ARCHITECTURE.md").write_text("# Architecture\n\nContent here.")
    verifier_node = make_verifier_node(workspace_root=str(tmp_path))

    # Also record a write_file tool result so the verifier can pick it up
    state = _base_state(
        tool_results=[
            {
                "tool": "write_file",
                "arguments": {"path": str(tmp_path / "ARCHITECTURE.md"), "content": "..."},
                "success": True,
                "content": f"Successfully wrote 30 characters to '{tmp_path / 'ARCHITECTURE.md'}'.",
            }
        ]
    )
    result = await verifier_node(state)
    report = result["verification_report"]
    signal = report.evaluate_outcome()

    assert signal.recommendation == "APPROVE"
    assert result["missing_artifacts"] == []


# ---------------------------------------------------------------------------
# 3: Delivery mode blocks exploration tools immediately
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delivery_mode_blocks_read_file(tmp_path: Any) -> None:
    """When delivery_mode=True, read_file calls must be rejected with RESEARCH PHASE COMPLETE."""
    tc = _make_tool_call("read_file", '{"path": "README.md"}')
    chat_service = _MockChatService([
        _make_ai_response(finish_reason="tool_calls", tool_calls=[tc]),
        _make_ai_response(content="done", finish_reason="stop"),
    ])

    registry = ToolRegistry()
    router = ToolRouter(registry)
    executor_node = make_executor_node(chat_service, registry, router)

    state = _base_state(delivery_mode=True, research_budget_remaining=0)
    result = await executor_node(state)

    failed = [tr for tr in result["tool_results"] if tr["tool"] == "read_file"]
    assert failed, "Expected a failed read_file result"
    assert failed[0]["success"] is False
    assert "RESEARCH PHASE COMPLETE" in failed[0]["error"]


@pytest.mark.anyio
async def test_delivery_mode_blocks_list_files(tmp_path: Any) -> None:
    """When delivery_mode=True, list_files calls must also be blocked."""
    tc = _make_tool_call("list_files", '{"path": "."}')
    chat_service = _MockChatService([
        _make_ai_response(finish_reason="tool_calls", tool_calls=[tc]),
        _make_ai_response(content="done", finish_reason="stop"),
    ])

    registry = ToolRegistry()
    router = ToolRouter(registry)
    executor_node = make_executor_node(chat_service, registry, router)

    state = _base_state(delivery_mode=True, research_budget_remaining=0)
    result = await executor_node(state)

    failed = [tr for tr in result["tool_results"] if tr["tool"] == "list_files"]
    assert failed[0]["success"] is False
    assert "RESEARCH PHASE COMPLETE" in failed[0]["error"]


# ---------------------------------------------------------------------------
# 4: Delivery guidance message injected when artifacts missing + delivery mode
# ---------------------------------------------------------------------------


def test_delivery_guidance_message_format() -> None:
    """_delivery_guidance must produce a well-formed system Message."""
    msg = _delivery_guidance(["ARCHITECTURE.md", "README.md"])
    assert msg.role == "system"
    assert "RESEARCH PHASE COMPLETE" in msg.content
    assert "ARCHITECTURE.md" in msg.content
    assert "README.md" in msg.content
    assert "write_file" in msg.content
    assert "Further repository exploration is prohibited" in msg.content


# ---------------------------------------------------------------------------
# 5: Budget exhaustion triggers delivery mode
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_research_budget_exhaustion_triggers_delivery_mode() -> None:
    """After RESEARCH_THRESHOLD exploration calls, delivery_mode must be True in output."""
    # Simulate state where research budget is already 0
    state = _base_state(
        research_budget_remaining=0,
        delivery_mode=False,
        tool_results=[
            {
                "tool": "read_file",
                "arguments": {"path": f"file{i}.py"},
                "success": True,
                "content": "content",
                "error": None,
            }
            for i in range(RESEARCH_THRESHOLD)
        ],
    )

    tc = _make_tool_call("read_file", '{"path": "extra.py"}')
    chat_service = _MockChatService([
        _make_ai_response(finish_reason="tool_calls", tool_calls=[tc]),
        _make_ai_response(content="done", finish_reason="stop"),
    ])

    registry = ToolRegistry()
    router = ToolRouter(registry)
    executor_node = make_executor_node(chat_service, registry, router)

    result = await executor_node(state)
    # delivery_mode must be activated
    assert result["delivery_mode"] is True


# ---------------------------------------------------------------------------
# 6–7: Retry memory
# ---------------------------------------------------------------------------


def test_retry_memory_accumulates_and_deduplicates() -> None:
    """_build_retry_memory must accumulate entries across retries and deduplicate."""
    state = _base_state(
        retry_memory={
            "completed_actions": ["- Tool 'read_file' succeeded with args: {}"],
            "failed_actions": ["- Tool 'write_file' failed"],
            "failed_validations": ["- Missing required artifact: ARCHITECTURE.md"],
            "reviewer_feedback": ["Previous feedback"],
            "failed_attempt_signatures": ["read_file:{}"],
        },
        tool_results=[
            {
                "tool": "write_file",
                "arguments": {"path": "out.md"},
                "success": False,
                "content": "error",
                "error": "permission denied",
            }
        ],
    )

    mem = _build_retry_memory(
        state,
        completed_actions=["- Tool 'run_command' succeeded"],
        failed_actions=["- Tool 'write_file' failed"],   # duplicate
        failed_validations=["- Missing required artifact: ARCHITECTURE.md"],  # duplicate
        feedback="New reviewer feedback",
    )

    # Deduplication: duplicate entries appear only once
    assert mem["failed_actions"].count("- Tool 'write_file' failed") == 1
    assert mem["failed_validations"].count("- Missing required artifact: ARCHITECTURE.md") == 1
    # New entries added
    assert "- Tool 'run_command' succeeded" in mem["completed_actions"]
    assert "New reviewer feedback" in mem["reviewer_feedback"]
    # Old entries preserved
    assert "Previous feedback" in mem["reviewer_feedback"]


def test_retry_memory_tracks_failed_signatures() -> None:
    """_build_retry_memory must record failed_attempt_signatures from tool_results."""
    state = _base_state(
        retry_memory=_empty_retry_memory(),
        tool_results=[
            {
                "tool": "write_file",
                "arguments": {"path": "out.md", "content": "text"},
                "success": False,
                "content": "error",
                "error": "permission denied",
            }
        ],
    )

    mem = _build_retry_memory(
        state,
        completed_actions=[],
        failed_actions=[],
        failed_validations=[],
        feedback=None,
    )

    expected_sig = _action_signature("write_file", {"path": "out.md", "content": "text"})
    assert expected_sig in mem["failed_attempt_signatures"]


# ---------------------------------------------------------------------------
# 8: Planner retry prompt includes memory sections
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_planner_retry_prompt_includes_memory() -> None:
    """Planner node must pass retry memory details when reviewer_feedback is set."""
    mock_plan = Plan(
        goal_summary="Create ARCHITECTURE.md",
        ordered_steps=["Write it"],
        required_artifacts=["ARCHITECTURE.md"],
    )

    captured_prompt: list[str] = []

    async def _mock_plan(prompt: str) -> tuple[Plan, str]:
        captured_prompt.append(prompt)
        return mock_plan, "{}"

    planner_svc = MagicMock()
    planner_svc.plan = _mock_plan

    state = _base_state(
        reviewer_feedback="[REJECTED]\n- ARCHITECTURE.md missing",
        retry_count=1,
        retry_memory={
            "completed_actions": ["- Tool 'read_file' succeeded"],
            "failed_actions": ["- Tool 'write_file' failed"],
            "failed_validations": ["- Missing required artifact: ARCHITECTURE.md"],
            "reviewer_feedback": ["Previous rejection message"],
            "failed_attempt_signatures": [],
        },
    )

    planner_node = make_planner_node(planner_svc)
    result = await planner_node(state)

    assert captured_prompt, "plan() should have been called"
    prompt_text = captured_prompt[0]

    assert "Completed Actions" in prompt_text
    assert "Previous Failures" in prompt_text
    assert "Failed Validations" in prompt_text
    assert "ARCHITECTURE.md" in prompt_text
    assert result["retry_count"] == 2
    assert "ARCHITECTURE.md" in result["required_artifacts"]


# ---------------------------------------------------------------------------
# 9: Reviewer deterministic gate
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reviewer_gate_rejects_on_missing_artifacts() -> None:
    """Reviewer must immediately reject without calling the LLM when missing_artifacts is set."""
    mock_chat_service = MagicMock()
    mock_chat_service.provider = MagicMock()
    mock_chat_service.provider.generate = AsyncMock(
        return_value=MagicMock(content="[APPROVED] Great job.")
    )

    reviewer_node = make_reviewer_node(mock_chat_service)

    state = _base_state(
        missing_artifacts=["ARCHITECTURE.md"],
        verification_report=None,
    )
    result = await reviewer_node(state)

    # LLM must NOT be called — deterministic gate fires first
    mock_chat_service.provider.generate.assert_not_called()
    assert "[REJECTED]" in result["reviewer_feedback"]
    assert "ARCHITECTURE.md" in result["reviewer_feedback"]
    assert result["status"] == "planning"


# ---------------------------------------------------------------------------
# 10: Robust tool parsing — malformed JSON
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_tool_router_rejects_malformed_json() -> None:
    """ToolRouter must return a structured INVALID_ARGUMENTS error on bad JSON."""
    from nakama_kun.tools.interfaces import BaseTool

    class _DummyTool(BaseTool):
        name = "dummy"
        description = "A dummy tool."
        parameters: dict[str, Any] = {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }

        async def execute(self, **kwargs: Any) -> ToolResult:
            return ToolResult(success=True, output="ok")

    registry = ToolRegistry()
    registry.register(_DummyTool())
    router = ToolRouter(registry)

    # Send a truncated / malformed JSON string
    result = await router.dispatch("dummy", '{"path": "src/nakama_kun/config/__init__.')
    assert result.success is False
    assert "INVALID_ARGUMENTS" in (result.error or "")
    assert "Malformed JSON" in (result.error or "")
    assert "Re-issue the tool call with valid JSON" in (result.error or "")


# ---------------------------------------------------------------------------
# 11: Robust tool parsing — missing required argument
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_tool_router_rejects_missing_required_arg() -> None:
    """ToolRouter must reject calls missing a required schema argument."""
    from nakama_kun.tools.interfaces import BaseTool

    class _PathTool(BaseTool):
        name = "path_tool"
        description = "Needs a path."
        parameters: dict[str, Any] = {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }

        async def execute(self, **kwargs: Any) -> ToolResult:
            return ToolResult(success=True, output="ok")

    registry = ToolRegistry()
    registry.register(_PathTool())
    router = ToolRouter(registry)

    result = await router.dispatch("path_tool", {})  # missing 'path'
    assert result.success is False
    assert "INVALID_ARGUMENTS" in (result.error or "")
    assert "Missing required argument" in (result.error or "")


# ---------------------------------------------------------------------------
# 12: Duplicate failure prevention via retry memory
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_duplicate_failed_tool_call_blocked_via_retry_memory() -> None:
    """A tool call whose signature appears in failed_attempt_signatures must be rejected."""
    tc = _make_tool_call("read_file", '{"path": "README.md"}')
    chat_service = _MockChatService([
        _make_ai_response(finish_reason="tool_calls", tool_calls=[tc]),
        _make_ai_response(content="done", finish_reason="stop"),
    ])

    registry = ToolRegistry()
    router = ToolRouter(registry)
    executor_node = make_executor_node(chat_service, registry, router)

    # Pre-populate the retry memory with the signature of this exact call
    sig = _action_signature("read_file", '{"path": "README.md"}')
    state = _base_state(
        retry_memory={
            **_empty_retry_memory(),
            "failed_attempt_signatures": [sig],
        }
    )

    result = await executor_node(state)
    failed = [tr for tr in result["tool_results"] if tr["tool"] == "read_file"]
    assert failed, "Expected a blocked read_file"
    assert failed[0]["success"] is False
    assert "already failed" in failed[0]["error"].lower()


# ---------------------------------------------------------------------------
# 13–15: Pure unit tests for helper functions
# ---------------------------------------------------------------------------


def test_paths_match_exact() -> None:
    assert _paths_match("ARCHITECTURE.md", "ARCHITECTURE.md") is True


def test_paths_match_suffix() -> None:
    assert _paths_match("ARCHITECTURE.md", "/workspace/ARCHITECTURE.md") is True


def test_paths_match_basename() -> None:
    assert _paths_match("docs/ARCHITECTURE.md", "/tmp/ARCHITECTURE.md") is True


def test_paths_no_match() -> None:
    assert _paths_match("ARCHITECTURE.md", "README.md") is False


def test_missing_required_artifacts_empty_when_all_created() -> None:
    required = ["ARCHITECTURE.md"]
    created = ["/workspace/ARCHITECTURE.md"]
    assert _missing_required_artifacts(required, created) == []


def test_missing_required_artifacts_returns_missing() -> None:
    required = ["ARCHITECTURE.md", "README.md"]
    created = ["/workspace/README.md"]
    missing = _missing_required_artifacts(required, created)
    assert "ARCHITECTURE.md" in missing
    assert "README.md" not in missing


def test_prioritize_tool_schemas_in_delivery_mode() -> None:
    schemas = [
        {"function": {"name": "list_files"}},
        {"function": {"name": "read_file"}},
        {"function": {"name": "write_file"}},
        {"function": {"name": "run_command"}},
    ]
    ordered = _prioritize_tool_schemas(schemas, delivery_mode=True)
    names = [s["function"]["name"] for s in ordered]
    assert names[0] == "write_file"
    # exploration tools must come last
    for ex in ["list_files", "read_file"]:
        assert names.index(ex) > names.index("write_file")


def test_prioritize_tool_schemas_noop_outside_delivery_mode() -> None:
    schemas = [
        {"function": {"name": "read_file"}},
        {"function": {"name": "write_file"}},
    ]
    ordered = _prioritize_tool_schemas(schemas, delivery_mode=False)
    assert ordered == schemas  # unchanged
