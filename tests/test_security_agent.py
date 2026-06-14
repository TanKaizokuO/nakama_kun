from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nakama_kun.agents.models import AgentMessage, SecurityReport
from nakama_kun.agents.security import SecurityAgent
from nakama_kun.agents.workspace import AgentWorkspace
from nakama_kun.agents.communication import AgentCommunicationLayer
from nakama_kun.ai.models.message import Message
from nakama_kun.ai.models.response import AIResponse, TokenUsage
from nakama_kun.orchestration.evidence import EvidenceStore, build_evidence_store
from nakama_kun.orchestration.state import AgentState
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


@pytest.mark.anyio
async def test_security_agent_secret_detection() -> None:
    # 1. Setup mock ChatService
    chat_service = MagicMock()
    mock_response = _make_ai_response(
        content='{"warnings": [], "vulnerabilities": [], "blocked_actions": [], "remediation_suggestions": []}'
    )
    chat_service.provider.generate = AsyncMock(return_value=mock_response)

    agent = SecurityAgent(chat_service)

    # 2. State with a hardcoded secret in coder proposals
    state = {
        "goal": "Write a python script",
        "coder_proposals": [
            {
                "path": "app.py",
                "content": 'api_key = "secret_value_12345"',
                "explanation": "Add credential"
            }
        ],
        "created_artifacts": [],
        "tool_results": []
    }

    res = await agent.execute(state)
    report = res["security_report"]

    assert isinstance(report, SecurityReport)
    # Our rule-based scanner should have caught it even if the LLM returned empty arrays
    assert len(report.vulnerabilities) > 0
    assert "api_key" in report.vulnerabilities[0].lower() or "secret" in report.vulnerabilities[0].lower()
    assert len(report.remediation_suggestions) > 0


@pytest.mark.anyio
async def test_security_agent_unsafe_command_detection() -> None:
    chat_service = MagicMock()
    mock_response = _make_ai_response(
        content='{"warnings": [], "vulnerabilities": [], "blocked_actions": [], "remediation_suggestions": []}'
    )
    chat_service.provider.generate = AsyncMock(return_value=mock_response)

    agent = SecurityAgent(chat_service)

    # State with destructive command executed in tool results
    state = {
        "goal": "Clean the workspace",
        "coder_proposals": [],
        "created_artifacts": [],
        "tool_results": [
            {
                "tool": "run_command",
                "arguments": {"CommandLine": "rm -rf /"},
                "success": True,
                "content": "Cleaned up"
            }
        ]
    }

    res = await agent.execute(state)
    report = res["security_report"]

    assert isinstance(report, SecurityReport)
    assert len(report.blocked_actions) > 0
    assert "rm -rf" in report.blocked_actions[0].lower()


@pytest.mark.anyio
async def test_agent_workspace_and_comms() -> None:
    # Verify AgentWorkspace read-only properties
    state = {
        "workspace_context": "Root workspace files",
        "retrieval_package": "retrieval_stub",
        "evidence_store": "evidence_stub",
        "plan": "plan_stub",
        "coder_proposals": [{"path": "main.py"}],
    }

    workspace = AgentWorkspace(state)
    assert workspace.repository_context == "Root workspace files"
    assert workspace.retrieval_results == "retrieval_stub"
    assert workspace.evidence == "evidence_stub"
    assert workspace.reports["plan"] == "plan_stub"
    assert workspace.reports["coder_proposals"] == [{"path": "main.py"}]

    # Verify AgentCommunicationLayer brokers messages in state
    comms = AgentCommunicationLayer(state)
    assert state["agent_messages"] == []

    # Send message
    comms.request_information("PlannerAgent", "RetrieverAgent", "Find files relating to DB")
    comms.share_findings("RetrieverAgent", "CoderAgent", {"files": ["db.py"]})
    comms.submit_recommendations("SecurityAgent", "ReviewerAgent", ["Remove unsafe rm command"])

    messages = comms.get_messages()
    assert len(messages) == 3
    assert messages[0].sender == "PlannerAgent"
    assert messages[0].message_type == "request_information"
    assert messages[1].receiver == "CoderAgent"
    assert messages[2].payload == {"recommendations": ["Remove unsafe rm command"]}

    # Filter messages
    retriever_msgs = comms.get_messages(receiver="RetrieverAgent")
    assert len(retriever_msgs) == 1
    assert retriever_msgs[0].sender == "PlannerAgent"


@pytest.mark.anyio
async def test_security_workflow_integration() -> None:
    chat_service = MagicMock()
    chat_service.provider = MagicMock()
    chat_service.provider.settings = MagicMock()
    chat_service.provider.settings.openrouter_model = "test-model"

    mock_plan_text = """Goal: Test task
    Target Files/Modules: []
    Assumptions: []
    Execution Steps:
    1. Step 1
    Risks & Hazards: []
    Validation Checklist: []
    """

    # We mock generate calls to simulate Planner, Retriever, Coder, TestAgent, SecurityAgent, Verifier, and Reviewer
    async def mock_generate(messages: list[Message], **kwargs: Any) -> AIResponse:
        sys_msgs = [m for m in messages if m.role == "system"]
        content_lower = "".join(m.content or "" for m in sys_msgs).lower()
        user_msgs = [m for m in messages if m.role == "user"]
        prompt_lower = "".join(m.content or "" for m in user_msgs).lower()

        if "reviewer" in content_lower or "reviewer" in prompt_lower:
            return _make_ai_response(
                '[APPROVED] ```json\n{"approved": true, "feedback": null, "route_to": null, "bugs": [], "risks": []}\n```'
            )
        elif "security" in content_lower or "security" in prompt_lower:
            # Return a security report with a warning to verify it is processed
            return _make_ai_response(
                '{"warnings": ["Potential security warning"], "vulnerabilities": [], "blocked_actions": [], "remediation_suggestions": []}'
            )
        elif "test" in content_lower or "test" in prompt_lower:
            return _make_ai_response(
                '{"passed": 1, "failed": 0, "skipped": 0, "errors": 0, "recommendations": []}'
            )
        elif "retriever" in content_lower or "retriever" in prompt_lower:
            return _make_ai_response(
                '{"retrieved_files": [], "summaries": {}, "citations": {}, "relevance_scores": {}}'
            )
        elif "synthesize" in prompt_lower or "synthesize" in content_lower:
            return _make_ai_response("Mock final response")
        else:
            # Planner response
            return _make_ai_response(mock_plan_text)

    chat_service.provider.generate = AsyncMock(side_effect=mock_generate)
    
    # Mock chat_with_tools for Coder loop
    chat_service.chat_with_tools = AsyncMock(return_value=_make_ai_response("Coder complete"))

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

    # Initial state
    initial_state = {
        "goal": "Verify security integration works",
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

    # The workflow should run to completion and record security reports/evidence
    assert res.get("status") == "done"
    assert res.get("security_report") is not None
    assert "Potential security warning" in res["security_report"].warnings
