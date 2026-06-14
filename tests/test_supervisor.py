from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nakama_kun.agents.models import (
    AgentMessage,
    SupervisorDecision,
    TaskDelegation,
    parse_supervisor_decision,
)
from nakama_kun.agents.registry import AgentCapabilityRegistry
from nakama_kun.agents.supervisor import SupervisorAgent
from nakama_kun.ai.models.message import Message
from nakama_kun.ai.models.response import AIResponse, TokenUsage
from nakama_kun.orchestration.state import merge_dicts, merge_lists
from nakama_kun.orchestration.workflow import build_agent_graph
from nakama_kun.tools import ToolRegistry, ToolRouter


def _make_ai_response(content: str) -> AIResponse:
    return AIResponse(
        content=content,
        model="test-model",
        usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        finish_reason="stop",
        latency=0.1,
    )


def test_agent_capability_registry() -> None:
    registry = AgentCapabilityRegistry()
    
    # 1. Verify default registrations
    coder = registry.get_agent("CoderAgent")
    assert coder is not None
    assert coder.role == "coder"
    assert "code generation" in coder.capabilities
    assert "write_file" in coder.tool_access

    security = registry.get_agent("SecurityAgent")
    assert security is not None
    assert security.role == "security"
    assert "security audit" in security.capabilities

    # 2. Verify listing and dictionary export
    agents = registry.list_agents()
    assert len(agents) == 7
    d = coder.to_dict()
    assert d["name"] == "CoderAgent"
    assert d["availability"] is True


def test_parse_supervisor_decision() -> None:
    valid_json = """
    {
      "rationale": "Need codebase context",
      "next_agents": ["RetrieverAgent"],
      "delegations": [
        {
          "task": "Retrieve DB files",
          "assigned_agent": "RetrieverAgent",
          "priority": 1,
          "dependencies": [],
          "status": "pending"
        }
      ],
      "status": "executing"
    }
    """
    decision = parse_supervisor_decision(valid_json)
    assert decision is not None
    assert decision.rationale == "Need codebase context"
    assert decision.next_agents == ["RetrieverAgent"]
    assert len(decision.delegations) == 1
    assert decision.delegations[0].assigned_agent == "RetrieverAgent"
    assert decision.status == "executing"

    # Test code block stripping
    markdown_json = f"```json\n{valid_json}\n```"
    decision_md = parse_supervisor_decision(markdown_json)
    assert decision_md is not None
    assert decision_md.rationale == "Need codebase context"


def test_reducers_merging() -> None:
    # 1. Merge dicts reducer
    left_dict = {"CoderAgent": {"duration_seconds": 1.2}}
    right_dict = {"SecurityAgent": {"duration_seconds": 0.8}}
    merged_d = merge_dicts(left_dict, right_dict)
    assert "CoderAgent" in merged_d
    assert "SecurityAgent" in merged_d
    assert merged_d["CoderAgent"]["duration_seconds"] == 1.2

    # 2. Merge lists reducer
    left_list = ["foo", "bar"]
    right_list = ["bar", "baz"]
    merged_l = merge_lists(left_list, right_list)
    assert merged_l == ["foo", "bar", "baz"]


@pytest.mark.anyio
async def test_supervisor_agent_fallback_and_telemetry() -> None:
    chat_service = MagicMock()
    # Mock generation to fail parsing, triggering the fallback scheduler
    chat_service.provider.generate = AsyncMock(return_value=_make_ai_response("Invalid JSON"))

    agent = SupervisorAgent(chat_service)

    # State with CoderAgent as active agent
    state = {
        "goal": "Write code",
        "active_agent": "CoderAgent",
        "agent_metrics": {
            "CoderAgent": {"duration_seconds": 2.5, "status": "executing"}
        },
        "agent_history": [
            {"agent": "CoderAgent", "thought": "implementing", "handoff": {}}
        ],
        "delegations": [
            {
                "task": "Fallback execution of CoderAgent",
                "assigned_agent": "CoderAgent",
                "priority": 1,
                "dependencies": [],
                "status": "pending",
            }
        ],
        "supervisor_telemetry": {
            "agent_utilization": {},
            "task_latency": [],
            "delegation_history": [],
            "failure_rates": {},
        }
    }

    res = await agent.run(state)
    assert res["status"] == "executing"
    
    # Fallback should schedule TestAgent after CoderAgent
    history_entry = res["agent_history"][0]
    assert "TestAgent" in history_entry["handoff"]["next_agents"]

    # Verify telemetry calculations
    telemetry = res["supervisor_telemetry"]
    assert telemetry["agent_utilization"]["CoderAgent"] == 1
    assert telemetry["task_latency"][0]["agent"] == "CoderAgent"
    assert telemetry["task_latency"][0]["duration_seconds"] == 2.5


@pytest.mark.anyio
async def test_supervisor_dynamic_routing_and_workflow() -> None:
    chat_service = MagicMock()
    chat_service.provider = MagicMock()
    chat_service.provider.settings = MagicMock()
    chat_service.provider.settings.openrouter_model = "test-model"

    # Define dynamic scheduling decisions for: Retriever -> Coder -> Reviewer (approved) -> done
    decisions = [
        # 1. Start: schedule Retriever
        SupervisorDecision(
            rationale="Explore codebase first.",
            next_agents=["RetrieverAgent"],
            delegations=[TaskDelegation(task="Search files", assigned_agent="RetrieverAgent")],
            status="executing"
        ),
        # 2. Retriever done: schedule Coder
        SupervisorDecision(
            rationale="Retrieve done, start code generation.",
            next_agents=["CoderAgent"],
            delegations=[
                TaskDelegation(task="Search files", assigned_agent="RetrieverAgent", status="completed"),
                TaskDelegation(task="Code feature", assigned_agent="CoderAgent")
            ],
            status="executing"
        ),
        # 3. Coder done: schedule Reviewer
        SupervisorDecision(
            rationale="Code complete, review implementation.",
            next_agents=["ReviewerAgent"],
            delegations=[
                TaskDelegation(task="Search files", assigned_agent="RetrieverAgent", status="completed"),
                TaskDelegation(task="Code feature", assigned_agent="CoderAgent", status="completed"),
                TaskDelegation(task="QA check", assigned_agent="ReviewerAgent")
            ],
            status="reviewing"
        ),
        # 4. Reviewer approved: finish task
        SupervisorDecision(
            rationale="Reviewer approved, finalize.",
            next_agents=["final_response"],
            delegations=[
                TaskDelegation(task="Search files", assigned_agent="RetrieverAgent", status="completed"),
                TaskDelegation(task="Code feature", assigned_agent="CoderAgent", status="completed"),
                TaskDelegation(task="QA check", assigned_agent="ReviewerAgent", status="completed")
            ],
            status="done"
        )
    ]

    # Mock generator returns supervisor decisions, reviewer outputs, and final response in order
    reviewer_handoff = '{"approved": true, "feedback": null, "route_to": null, "bugs": [], "risks": []}'
    
    mock_responses = [
        # 1st Supervisor run
        _make_ai_response(decisions[0].model_dump_json()),
        # RetrieverAgent execute runs
        _make_ai_response('{"retrieved_files": [], "summaries": {}, "citations": {}, "relevance_scores": {}}'),
        # 2nd Supervisor run
        _make_ai_response(decisions[1].model_dump_json()),
        # 3rd Supervisor run
        _make_ai_response(decisions[2].model_dump_json()),
        # ReviewerAgent runs
        _make_ai_response(reviewer_handoff),
        # 4th Supervisor run
        _make_ai_response(decisions[3].model_dump_json()),
        # final_response node
        _make_ai_response("Final supervisor response completed successfully.")
    ]

    chat_service.provider.generate = AsyncMock(side_effect=mock_responses)
    chat_service.chat_with_tools = AsyncMock(return_value=_make_ai_response("Coder execute complete"))

    planner_svc = MagicMock()
    planner_svc._chat_service = chat_service

    # Build the multi-agent graph
    registry = ToolRegistry()
    router = ToolRouter(registry)
    graph = build_agent_graph(
        chat_service=chat_service,
        planner_service=planner_svc,
        tool_registry=registry,
        tool_router=router,
    ).compile()

    initial_state = {
        "goal": "Write dynamic supervisor test case",
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
        "retrieval_package": None,
        "test_report": None,
        "security_report": None,
        "agent_messages": [],
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
    assert res["final_response"] == "Final supervisor response completed successfully."
    
    # Telemetry should be populated
    util = res["supervisor_telemetry"]["agent_utilization"]
    assert util.get("RetrieverAgent", 0) >= 1
    assert util.get("CoderAgent", 0) >= 1
    assert util.get("ReviewerAgent", 0) >= 1
