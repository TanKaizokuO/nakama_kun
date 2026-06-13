from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nakama_kun.agents.coder import CoderAgent, parse_coder_handoff
from nakama_kun.agents.executor import ExecutorAgent
from nakama_kun.agents.planner import PlannerAgent
from nakama_kun.agents.reviewer import ReviewerAgent, parse_reviewer_handoff
from nakama_kun.ai.models.message import ToolCall
from nakama_kun.ai.models.plan import Plan
from nakama_kun.ai.models.response import AIResponse
from nakama_kun.ai.services.chat_service import ChatService
from nakama_kun.orchestration.verification import (
    CommandResult,
    FileArtifact,
    VerificationReport,
)
from nakama_kun.tools import ToolRegistry, ToolRouter


@pytest.fixture
def mock_chat_service() -> MagicMock:
    service = MagicMock(spec=ChatService)
    service.provider = MagicMock()
    service.provider.generate = AsyncMock()
    service.chat_with_tools = AsyncMock()
    return service


def test_parse_coder_handoff() -> None:
    # Test valid json directly
    raw_json = '{"proposals": [{"path": "a.txt", "content": "hello", "explanation": "test"}], "notes": "some notes"}'
    res = parse_coder_handoff(raw_json)
    assert res is not None
    assert len(res.proposals) == 1
    assert res.proposals[0].path == "a.txt"
    assert res.notes == "some notes"

    # Test markdown json block
    markdown = f"Here is the plan:\n```json\n{raw_json}\n```"
    res = parse_coder_handoff(markdown)
    assert res is not None
    assert res.proposals[0].content == "hello"

    # Test invalid json
    assert parse_coder_handoff("invalid") is None


def test_parse_reviewer_handoff() -> None:
    raw_json = '{"approved": false, "feedback": "bug here", "route_to": "coder", "bugs": ["syntax"], "risks": []}'
    res = parse_reviewer_handoff(raw_json)
    assert res is not None
    assert res.approved is False
    assert res.route_to == "coder"
    assert "syntax" in res.bugs

    markdown = f"Review done:\n```json\n{raw_json}\n```"
    res = parse_reviewer_handoff(markdown)
    assert res is not None
    assert res.approved is False

    assert parse_reviewer_handoff("invalid") is None


@pytest.mark.anyio
async def test_planner_agent_run(mock_chat_service: MagicMock) -> None:
    agent = PlannerAgent(mock_chat_service)
    
    plan_text = json.dumps({
        "goal_summary": "Build calculator",
        "assumptions": ["Python 3"],
        "ordered_steps": ["Write add function"],
        "required_artifacts": ["calculator.py"],
        "risks": ["None"],
        "validation_checklist": ["Test calculator"],
        "targets": ["calculator.py"]
    })
    mock_chat_service.provider.generate.return_value = AIResponse(
        content=plan_text, finish_reason="stop", model="mock-model"
    )

    state: dict[str, Any] = {
        "goal": "Build calculator",
        "reviewer_feedback": None,
        "retry_count": 0,
        "agent_history": [],
    }

    res = await agent.run(state)
    assert res["plan"] is not None
    assert res["plan"].goal_summary == "Build calculator"
    assert "calculator.py" in res["plan"].targets
    assert len(res["agent_history"]) == 1
    assert res["agent_history"][0]["agent"] == "PlannerAgent"
    assert "Planner proposed Plan" in res["messages"][0].content


@pytest.mark.anyio
async def test_coder_agent_run(mock_chat_service: MagicMock) -> None:
    agent = CoderAgent(mock_chat_service)

    raw_handoff = '{"proposals": [{"path": "calculator.py", "content": "def add(a, b): return a + b", "explanation": "implement add"}], "notes": "coder notes"}'
    mock_chat_service.provider.generate.return_value = AIResponse(
        content=raw_handoff, finish_reason="stop", model="mock-model"
    )

    plan = Plan(
        goal_summary="Build calculator",
        targets=["calculator.py"],
        assumptions=[],
        ordered_steps=["Write add"],
        risks=[],
        validation_checklist=[],
    )
    state: dict[str, Any] = {
        "goal": "Build calculator",
        "plan": plan,
        "reviewer_feedback": None,
        "agent_history": [],
    }

    res = await agent.run(state)
    assert len(res["coder_proposals"]) == 1
    assert res["coder_proposals"][0]["path"] == "calculator.py"
    assert res["coder_proposals"][0]["content"] == "def add(a, b): return a + b"
    assert len(res["agent_history"]) == 1
    assert res["agent_history"][0]["agent"] == "CoderAgent"


@pytest.mark.anyio
async def test_executor_agent_run(mock_chat_service: MagicMock) -> None:
    registry = MagicMock(spec=ToolRegistry)
    registry.all_schemas.return_value = []
    
    router = MagicMock(spec=ToolRouter)
    mock_tool_res = MagicMock()
    mock_tool_res.success = True
    mock_tool_res.to_content.return_value = "Success"
    mock_tool_res.error = None
    router.dispatch.return_value = mock_tool_res

    agent = ExecutorAgent(mock_chat_service, registry, router)

    # Round 1: generate tool call
    mock_tc = ToolCall(
        id="tc-1",
        function={"name": "write_file", "arguments": {"path": "calculator.py", "content": "xyz"}},
    )
    resp_1 = AIResponse(content="Calling write", tool_calls=[mock_tc], finish_reason="tool_calls", model="mock-model")
    
    # Round 2: stop
    resp_2 = AIResponse(content="Done", tool_calls=[], finish_reason="stop", model="mock-model")

    mock_chat_service.chat_with_tools.side_effect = [resp_1, resp_2]

    state: dict[str, Any] = {
        "goal": "Build calculator",
        "plan": None,
        "messages": [],
        "tool_results": [],
        "required_artifacts": ["calculator.py"],
        "created_artifacts": [],
        "research_budget_remaining": 10,
        "delivery_mode": False,
        "agent_history": [],
    }

    res = await agent.run(state)
    assert len(res["tool_results"]) == 1
    assert res["tool_results"][0]["tool"] == "write_file"
    assert res["tool_results"][0]["success"] is True
    assert "calculator.py" in res["created_artifacts"]
    assert len(res["agent_history"]) == 1
    assert res["agent_history"][0]["agent"] == "ExecutorAgent"


@pytest.mark.anyio
async def test_reviewer_agent_approved(mock_chat_service: MagicMock) -> None:
    agent = ReviewerAgent(mock_chat_service)

    raw_handoff = '{"approved": true, "feedback": null, "route_to": null, "bugs": [], "risks": []}'
    mock_chat_service.provider.generate.return_value = AIResponse(
        content=raw_handoff, finish_reason="stop", model="mock-model"
    )

    report = VerificationReport(
        files_created=[],
        files_modified=[],
        existence_checks=[],
        command_results=[],
        workspace_snapshot=[],
        summary="All checks passed."
    )
    
    state: dict[str, Any] = {
        "goal": "Build calculator",
        "plan": None,
        "verification_report": report,
        "agent_history": [],
    }

    res = await agent.run(state)
    assert res["reviewer_feedback"] is None
    assert res["reviewer_route"] is None
    assert res["status"] == "done"
    assert len(res["agent_history"]) == 1
    assert res["agent_history"][0]["handoff"]["approved"] is True


@pytest.mark.anyio
async def test_reviewer_agent_rejected(mock_chat_service: MagicMock) -> None:
    agent = ReviewerAgent(mock_chat_service)

    # Reviewer rejects and routes to coder
    raw_handoff = '{"approved": false, "feedback": "Syntax error in calculator.py", "route_to": "coder", "bugs": ["syntax"], "risks": []}'
    mock_chat_service.provider.generate.return_value = AIResponse(
        content=raw_handoff, finish_reason="stop", model="mock-model"
    )

    report = VerificationReport(
        files_created=[],
        files_modified=[],
        existence_checks=[],
        command_results=[],
        workspace_snapshot=[],
        summary="Tests failed."
    )
    
    state: dict[str, Any] = {
        "goal": "Build calculator",
        "plan": None,
        "verification_report": report,
        "agent_history": [],
    }

    res = await agent.run(state)
    assert res["reviewer_feedback"] == "Syntax error in calculator.py"
    assert res["reviewer_route"] == "coder"
    assert res["status"] == "planning"
    assert len(res["agent_history"]) == 1
    assert res["agent_history"][0]["handoff"]["approved"] is False
    assert res["agent_history"][0]["handoff"]["route_to"] == "coder"


@pytest.mark.anyio
async def test_reviewer_agent_fallback_outcome_signal(mock_chat_service: MagicMock) -> None:
    agent = ReviewerAgent(mock_chat_service)

    # Let the generate response be completely invalid JSON to trigger fallback
    mock_chat_service.provider.generate.return_value = AIResponse(
        content="This is plain text with no json.", finish_reason="stop", model="mock-model"
    )

    report = VerificationReport(
        files_created=[FileArtifact(path="calculator.py", exists=True, content_snippet="xyz", size_bytes=100)],
        files_modified=[],
        existence_checks=[],
        command_results=[CommandResult(cmd="pytest", exit_code=1, stdout_snippet="", success=False)],
        workspace_snapshot=[],
        summary="Tests failed."
    )
    
    state: dict[str, Any] = {
        "goal": "Build calculator",
        "plan": None,
        "verification_report": report,
        "agent_history": [],
    }

    # OutcomeSignal recommends rejection because pytest failed
    res = await agent.run(state)
    assert res["reviewer_feedback"] is not None
    assert res["reviewer_route"] == "coder"  # routed to coder because tests failed
    assert res["status"] == "planning"
    assert len(res["agent_history"]) == 1
    assert res["agent_history"][0]["handoff"]["approved"] is False
