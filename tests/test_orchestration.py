from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nakama_kun.ai.models.plan import Plan
from nakama_kun.ai.models.response import AIResponse
from nakama_kun.ai.services.chat_service import ChatService
from nakama_kun.ai.services.planner_service import PlannerService
from nakama_kun.orchestration.nodes import (
    make_executor_node,
    make_final_response_node,
    make_planner_node,
    make_reviewer_node,
    make_verifier_node,
)
from nakama_kun.orchestration.state import AgentState
from nakama_kun.orchestration.workflow import build_agent_graph, route_after_review
from nakama_kun.tools import ToolRegistry, ToolRouter


@pytest.fixture
def mock_chat_service() -> MagicMock:
    """Fixture returning a mock ChatService."""
    service = MagicMock(spec=ChatService)
    service.provider = MagicMock()
    service.provider.generate = AsyncMock()
    service.chat_with_tools = AsyncMock()
    return service


@pytest.fixture
def mock_planner_service() -> MagicMock:
    """Fixture returning a mock PlannerService."""
    service = MagicMock(spec=PlannerService)
    service.plan = AsyncMock()
    return service


@pytest.mark.anyio
async def test_planner_node(mock_planner_service: MagicMock) -> None:
    """Verify Planner node generates and updates plan state."""
    mock_plan = Plan(
        goal_summary="Summary of goal",
        targets=["test.py"],
        assumptions=[],
        ordered_steps=["Step 1"],
        risks=[],
        validation_checklist=[],
    )
    mock_planner_service.plan.return_value = (mock_plan, "Plan raw details")

    planner_node = make_planner_node(mock_planner_service)

    state: AgentState = {
        "goal": "Write a python file",
        "plan": None,
        "messages": [],
        "tool_results": [],
        "verification_report": None,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "planning",
    }

    result = await planner_node(state)
    assert result["plan"] == mock_plan
    assert result["status"] == "executing"
    assert result["retry_count"] == 0
    assert len(result["messages"]) == 1

    # Test refinement when reviewer feedback exists
    state_feedback: AgentState = {
        "goal": "Write a python file",
        "plan": None,
        "messages": [],
        "tool_results": [],
        "verification_report": None,
        "reviewer_feedback": "Syntax error in file.",
        "retry_count": 1,
        "final_response": None,
        "status": "planning",
    }
    result_refine = await planner_node(state_feedback)
    assert result_refine["retry_count"] == 2


@pytest.mark.anyio
async def test_executor_node(mock_chat_service: MagicMock) -> None:
    """Verify Executor node invokes tools and logs tool executions."""
    from nakama_kun.ai.models.message import ToolCall

    # Setup mock LLM response requesting tool call
    mock_tc = ToolCall(
        id="tc-1",
        function={"name": "write_file", "arguments": {"path": "a.txt", "content": "hello"}},
    )

    mock_llm_response = MagicMock(spec=AIResponse)
    mock_llm_response.finish_reason = "tool_calls"
    mock_llm_response.content = None
    mock_llm_response.tool_calls = [mock_tc]

    # Setup second response indicating completion
    mock_llm_finish = MagicMock(spec=AIResponse)
    mock_llm_finish.finish_reason = "stop"
    mock_llm_finish.content = "All set."
    mock_llm_finish.tool_calls = []

    mock_chat_service.chat_with_tools.side_effect = [mock_llm_response, mock_llm_finish]

    registry = MagicMock(spec=ToolRegistry)
    registry.all_schemas.return_value = []
    
    router = MagicMock(spec=ToolRouter)
    mock_tool_result = MagicMock()
    mock_tool_result.success = True
    mock_tool_result.to_content.return_value = "File written successfully."
    router.dispatch.return_value = mock_tool_result

    executor_node = make_executor_node(mock_chat_service, registry, router)

    state: AgentState = {
        "goal": "Write file",
        "plan": None,
        "messages": [],
        "tool_results": [],
        "verification_report": None,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "executing",
    }

    result = await executor_node(state)
    assert result["status"] == "reviewing"
    assert len(result["tool_results"]) == 1
    assert result["tool_results"][0]["tool"] == "write_file"
    assert result["tool_results"][0]["success"] is True
    assert len(result["messages"]) == 3  # Assistant (tool_call) + Tool (result) + Assistant (finish)


@pytest.mark.anyio
async def test_reviewer_node(mock_chat_service: MagicMock) -> None:
    """Verify Reviewer node approves or rejects execution based on LLM QA outputs."""
    reviewer_node = make_reviewer_node(mock_chat_service)

    state: AgentState = {
        "goal": "Write file",
        "plan": None,
        "messages": [],
        "tool_results": [],
        "verification_report": None,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "reviewing",
    }

    # Test APPROVED flow
    mock_response_appr = MagicMock(spec=AIResponse)
    mock_response_appr.content = "[APPROVED] All tasks met."
    mock_chat_service.provider.generate.return_value = mock_response_appr

    result_appr = await reviewer_node(state)
    assert result_appr["reviewer_feedback"] is None
    assert result_appr["status"] == "done"

    # Test REJECTED flow
    mock_response_rej = MagicMock(spec=AIResponse)
    mock_response_rej.content = "[REJECTED] The python script has formatting bugs."
    mock_chat_service.provider.generate.return_value = mock_response_rej

    result_rej = await reviewer_node(state)
    assert "[REJECTED]" in result_rej["reviewer_feedback"]
    assert result_rej["status"] == "planning"


def test_routing_logic() -> None:
    """Verify conditional edges route properly based on feedback and retry counts."""
    # Approved → Final Response
    state_appr: AgentState = {
        "goal": "Write file",
        "plan": None,
        "messages": [],
        "tool_results": [],
        "verification_report": None,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "reviewing",
    }
    assert route_after_review(state_appr) == "final_response"

    # Rejected + Retry < 3 → Planner
    state_rej: AgentState = {
        "goal": "Write file",
        "plan": None,
        "messages": [],
        "tool_results": [],
        "verification_report": None,
        "reviewer_feedback": "Errors present.",
        "retry_count": 1,
        "final_response": None,
        "status": "reviewing",
    }
    assert route_after_review(state_rej) == "planner"

    # Rejected + Retry >= 3 → Final Response (Limit reached)
    state_limit: AgentState = {
        "goal": "Write file",
        "plan": None,
        "messages": [],
        "tool_results": [],
        "verification_report": None,
        "reviewer_feedback": "Errors present.",
        "retry_count": 3,
        "final_response": None,
        "status": "reviewing",
    }
    assert route_after_review(state_limit) == "final_response"


@pytest.mark.anyio
async def test_final_response_node(mock_chat_service: MagicMock) -> None:
    """Verify Final Response node generates a summary."""
    final_response_node = make_final_response_node(mock_chat_service)
    
    mock_response = MagicMock(spec=AIResponse)
    mock_response.content = "Summary of operations."
    mock_chat_service.provider.generate.return_value = mock_response

    state: AgentState = {
        "goal": "Write file",
        "plan": None,
        "messages": [],
        "tool_results": [],
        "verification_report": None,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "done",
    }

    result = await final_response_node(state)
    assert result["final_response"] == "Summary of operations."
    assert result["status"] == "done"


def test_build_agent_graph(mock_chat_service: MagicMock, mock_planner_service: MagicMock) -> None:
    """Verify the stategraph workflow compiles successfully with verifier node."""
    registry = MagicMock(spec=ToolRegistry)
    router = MagicMock(spec=ToolRouter)

    graph = build_agent_graph(
        chat_service=mock_chat_service,
        planner_service=mock_planner_service,
        tool_registry=registry,
        tool_router=router,
        workspace_root="/tmp/test_workspace",
    )
    compiled = graph.compile()
    assert compiled is not None


@pytest.mark.anyio
async def test_verifier_node_in_orchestration(tmp_path: Any) -> None:
    """Verify make_verifier_node returns a working async node that stores a report."""
    import pathlib

    from nakama_kun.orchestration.verification import VerificationReport

    workspace = str(tmp_path)
    target_file = str(tmp_path / "result.py")
    pathlib.Path(target_file).write_text("x = 42", encoding="utf-8")

    verifier_node = make_verifier_node(workspace_root=workspace)

    state: AgentState = {
        "goal": "Write result.py",
        "plan": None,
        "messages": [],
        "tool_results": [
            {
                "tool": "write_file",
                "arguments": {"path": target_file, "content": "x = 42"},
                "success": True,
                "content": f"Successfully wrote 6 characters to '{target_file}'.",
            }
        ],
        "verification_report": None,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "reviewing",
    }

    result = await verifier_node(state)
    report = result["verification_report"]
    assert isinstance(report, VerificationReport)
    assert result["status"] == "reviewing"
    # The file exists on disk — verifier should detect it
    assert len(report.files_created) == 1
    assert report.files_created[0].exists is True
    assert "x = 42" in report.files_created[0].content_snippet


@pytest.mark.anyio
async def test_planner_node_retry_state_verification(mock_planner_service: MagicMock) -> None:
    """Verify that planner node increments retry count and updates state correctly with feedback."""
    mock_plan = Plan(
        goal_summary="Summary of goal",
        targets=["test.py"],
        assumptions=[],
        ordered_steps=["Step 1"],
        risks=[],
        validation_checklist=[],
    )
    mock_planner_service.plan.return_value = (mock_plan, "Plan raw details")

    planner_node = make_planner_node(mock_planner_service)

    state: AgentState = {
        "goal": "Write python file",
        "plan": mock_plan,
        "messages": [],
        "tool_results": [],
        "verification_report": None,
        "reviewer_feedback": "Please fix issues.",
        "retry_count": 2,
        "final_response": None,
        "status": "planning",
    }

    result = await planner_node(state)
    assert result["retry_count"] == 3
    assert result["status"] == "executing"
    assert result["plan"] == mock_plan

