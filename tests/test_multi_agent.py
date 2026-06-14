from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nakama_kun.agents.base import BaseAgent
from nakama_kun.agents.planner import PlannerAgent
from nakama_kun.agents.coder import CoderAgent
from nakama_kun.agents.verifier import VerifierAgent
from nakama_kun.agents.reviewer import ReviewerAgent
from nakama_kun.ai.models.message import Message, ToolCall
from nakama_kun.ai.models.plan import Plan
from nakama_kun.ai.models.response import AIResponse
from nakama_kun.ai.services.chat_service import ChatService
from nakama_kun.orchestration.workflow import build_agent_graph
from nakama_kun.tools import ToolRegistry, ToolRouter


@pytest.fixture
def mock_chat_service() -> MagicMock:
    service = MagicMock(spec=ChatService)
    service.provider = MagicMock()
    service.provider.generate = AsyncMock()
    service.chat_with_tools = AsyncMock()
    return service


class DummyAgent(BaseAgent):
    def __init__(self, chat_service: Any) -> None:
        super().__init__(
            name="DummyAgent",
            role="coder",
            system_prompt="system",
            chat_service=chat_service,
        )

    async def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "executing",
            "coder_proposals": [],
            "tool_results": [{"tool": "dummy", "success": True}],
            "agent_history": [{"agent": "DummyAgent", "thought": "ran", "handoff": {}}],
        }


@pytest.mark.anyio
async def test_base_agent_routing_and_metrics_tracking(mock_chat_service: MagicMock) -> None:
    agent = DummyAgent(mock_chat_service)
    assert agent.name == "DummyAgent"
    assert agent.role == "coder"
    assert agent.system_prompt == "system"

    state = {
        "agent_history": [],
        "agent_outputs": {},
        "agent_metrics": {},
    }

    res = await agent.run(state)
    assert res["active_agent"] == "DummyAgent"
    assert "DummyAgent" in res["agent_outputs"]
    assert "DummyAgent" in res["agent_metrics"]
    assert res["agent_metrics"]["DummyAgent"]["status"] == "executing"
    assert len(agent.memory["implementation_history"]) == 1


@pytest.mark.anyio
async def test_planner_agent_plan_creation(mock_chat_service: MagicMock) -> None:
    agent = PlannerAgent(mock_chat_service)
    
    plan_text = json.dumps({
        "goal_summary": "Test decomposition",
        "assumptions": ["Python"],
        "ordered_steps": ["Write test"],
        "required_artifacts": ["test.py"],
        "risks": [],
        "validation_checklist": [],
        "targets": []
    })
    mock_chat_service.provider.generate.return_value = AIResponse(
        content=plan_text, finish_reason="stop", model="mock-model"
    )

    state = {
        "goal": "Write a test file",
        "reviewer_feedback": None,
        "retry_count": 0,
        "agent_history": [],
        "agent_outputs": {},
        "agent_metrics": {},
    }

    res = await agent.run(state)
    assert res["plan"].goal_summary == "Test decomposition"
    assert res["active_agent"] == "PlannerAgent"
    # Verify memory contains successful plans
    assert len(agent.successful_plans) == 1
    assert agent.successful_plans[0]["goal_summary"] == "Test decomposition"


@pytest.mark.anyio
async def test_verifier_agent_execution() -> None:
    with patch("nakama_kun.agents.verifier.VerificationLayer") as mock_layer_cls, \
         patch("nakama_kun.agents.verifier.build_evidence_store") as mock_build_store:
        
        mock_layer = MagicMock()
        mock_report = MagicMock()
        mock_report.files_created = []
        mock_report.files_modified = []
        mock_report.command_results = []
        mock_report.summary = "Checks ok"
        mock_layer.run.return_value = mock_report
        mock_layer_cls.return_value = mock_layer

        mock_build_store.return_value = "evidence_store_obj"

        agent = VerifierAgent(workspace_root="/tmp", chat_service=MagicMock())
        state = {
            "required_artifacts": ["test.py"],
            "created_artifacts": ["test.py"],
            "agent_history": [],
            "agent_outputs": {},
            "agent_metrics": {},
        }

        res = await agent.run(state)
        assert res["verification_report"] == mock_report
        assert res["evidence_store"] == "evidence_store_obj"
        assert len(res["missing_artifacts"]) == 0
        assert len(agent.validation_history) == 1


@pytest.mark.anyio
async def test_reviewer_agent_decision(mock_chat_service: MagicMock) -> None:
    agent = ReviewerAgent(mock_chat_service)

    raw_handoff = '{"approved": true, "feedback": null, "route_to": null, "bugs": [], "risks": []}'
    mock_chat_service.provider.generate.return_value = AIResponse(
        content=raw_handoff, finish_reason="stop", model="mock-model"
    )

    state = {
        "goal": "Test goal",
        "plan": None,
        "verification_report": None,
        "agent_history": [],
        "agent_outputs": {},
        "agent_metrics": {},
        "status": "reviewing",
        "goal_satisfied": False,
    }

    res = await agent.run(state)
    assert res["status"] == "done"
    assert res["reviewer_feedback"] is None
    assert len(agent.review_history) == 1


@pytest.mark.anyio
async def test_graph_wiring_and_handoffs(mock_chat_service: MagicMock) -> None:
    # Build components for compilation
    planner_service = MagicMock()
    registry = MagicMock(spec=ToolRegistry)
    registry.all_schemas.return_value = []
    
    router = MagicMock(spec=ToolRouter)
    mock_tool_res = MagicMock()
    mock_tool_res.success = True
    mock_tool_res.to_content.return_value = "Success"
    router.dispatch.return_value = mock_tool_res

    graph = build_agent_graph(
        chat_service=mock_chat_service,
        planner_service=planner_service,
        tool_registry=registry,
        tool_router=router,
        workspace_root="/tmp",
    ).compile()

    # Stub generated mock calls for Planner and Coder agent
    plan_text = json.dumps({
        "goal_summary": "Summary",
        "assumptions": [],
        "ordered_steps": [],
        "required_artifacts": [],
        "risks": [],
        "validation_checklist": [],
        "targets": []
    })
    
    # Planner response
    mock_chat_service.provider.generate.return_value = AIResponse(
        content=plan_text, finish_reason="stop", model="mock-model"
    )

    # Coder responses (execute loop calls)
    resp_stop = AIResponse(content="Done", tool_calls=[], finish_reason="stop", model="mock-model")
    mock_chat_service.chat_with_tools.return_value = resp_stop
    
    with patch("nakama_kun.agents.reviewer.ReviewerAgent.review") as mock_rev_review, \
         patch("nakama_kun.agents.verifier.VerifierAgent.execute") as mock_ver_execute:
        
        mock_ver_execute.return_value = {
            "verification_report": MagicMock(),
            "evidence_store": MagicMock(),
            "created_artifacts": [],
            "missing_artifacts": [],
            "status": "reviewing",
            "agent_history": [{"agent": "VerifierAgent", "thought": "checks passed", "handoff": {}}],
            "messages": [],
        }

        mock_rev_review.return_value = {
            "reviewer_feedback": None,
            "reviewer_route": None,
            "status": "done",
            "agent_history": [{"agent": "ReviewerAgent", "thought": "approved", "handoff": {"approved": True}}],
            "messages": [],
        }

        initial_state = {
            "goal": "Build it",
            "plan": None,
            "required_artifacts": [],
            "created_artifacts": [],
            "missing_artifacts": [],
            "research_budget_remaining": 15,
            "delivery_mode": False,
            "retry_memory": {
                "completed_actions": [],
                "failed_actions": [],
                "failed_validations": [],
                "reviewer_feedback": [],
                "failed_attempt_signatures": [],
            },
            "messages": [],
            "tool_results": [],
            "reviewer_feedback": None,
            "retry_count": 0,
            "final_response": None,
            "status": "planning",
            "goal_satisfied": False,
            "active_agent": "",
            "agent_outputs": {},
            "agent_metrics": {},
            "delegations": [],
            "supervisor_telemetry": {
                "agent_utilization": {},
                "task_latency": [],
                "delegation_history": [],
                "failure_rates": {},
            },
        }

        res = await graph.ainvoke(initial_state)
        assert res["status"] == "done"
        assert res["active_agent"] == "SupervisorAgent"
