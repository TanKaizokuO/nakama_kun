from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nakama_kun.agents.retriever import RetrieverAgent
from nakama_kun.agents.test_agent import TestAgent
from nakama_kun.agents.models import RetrievalPackage, TestExecutionReport
from nakama_kun.ai.models.message import Message, ToolCall
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


@pytest.mark.anyio
async def test_retriever_agent_execution(mock_chat_service: MagicMock) -> None:
    agent = RetrieverAgent(chat_service=mock_chat_service, workspace_root="/tmp")
    assert agent.name == "RetrieverAgent"
    assert agent.role == "retriever"

    mock_pkg = {
        "retrieved_files": ["foo.py"],
        "summaries": {"foo.py": "Implements Foo class"},
        "citations": {"foo.py": "Source: foo.py"},
        "relevance_scores": {"foo.py": 0.95}
    }
    
    mock_chat_service.provider.generate.return_value = AIResponse(
        content=json.dumps(mock_pkg), finish_reason="stop", model="mock-model"
    )

    state = {
        "goal": "Retrieve foo component",
        "agent_history": [],
        "agent_outputs": {},
        "agent_metrics": {},
    }

    # Patch the RAG retrieval calls
    with patch("nakama_kun.agents.retriever.get_retriever") as mock_get_ret:
        mock_ret = MagicMock()
        mock_res = MagicMock()
        mock_res.source_path = "foo.py"
        mock_res.source_type = "python_source"
        mock_res.score = 0.95
        mock_res.content = "def foo(): pass"
        mock_ret.retrieve.return_value = [mock_res]
        mock_get_ret.return_value = mock_ret

        res = await agent.run(state)
        assert res["active_agent"] == "RetrieverAgent"
        assert isinstance(res["retrieval_package"], RetrievalPackage)
        assert res["retrieval_package"].retrieved_files == ["foo.py"]
        assert "foo.py" in res["relevant_files"]
        assert "foo.py" in res["agent_outputs"]["RetrieverAgent"].retrieved_files


@pytest.mark.anyio
async def test_test_agent_execution(mock_chat_service: MagicMock) -> None:
    registry = MagicMock(spec=ToolRegistry)
    registry.all_schemas.return_value = []
    
    router = MagicMock(spec=ToolRouter)
    mock_tool_res = MagicMock()
    mock_tool_res.success = True
    mock_tool_res.to_content.return_value = "Pytest passed"
    mock_tool_res.error = None
    router.dispatch.return_value = mock_tool_res

    agent = TestAgent(chat_service=mock_chat_service, tool_registry=registry, tool_router=router)
    assert agent.name == "TestAgent"
    assert agent.role == "tester"

    # Step 1: LLM wants to execute tool
    tc = ToolCall(
        id="tc-test",
        function={"name": "run_command", "arguments": {"cmd": "pytest tests/test_foo.py"}},
    )
    resp_tool = AIResponse(content="Running test suite", tool_calls=[tc], finish_reason="tool_calls", model="mock-model")
    
    # Step 2: LLM finishes tool round
    resp_stop = AIResponse(content="Done", tool_calls=[], finish_reason="stop", model="mock-model")
    mock_chat_service.chat_with_tools.side_effect = [resp_tool, resp_stop]

    # Step 3: LLM generates final report
    mock_report = {
        "passed": 4,
        "failed": 0,
        "skipped": 1,
        "errors": 0,
        "recommendations": ["No recommendations, tests are green."]
    }
    mock_chat_service.provider.generate.return_value = AIResponse(
        content=json.dumps(mock_report), finish_reason="stop", model="mock-model"
    )

    state = {
        "goal": "Verify foo implementation",
        "created_artifacts": ["foo.py"],
        "tool_results": [],
        "messages": [],
        "agent_history": [],
        "agent_outputs": {},
        "agent_metrics": {},
    }

    res = await agent.run(state)
    assert res["active_agent"] == "TestAgent"
    assert isinstance(res["test_report"], TestExecutionReport)
    assert res["test_report"].passed == 4
    assert res["test_report"].failed == 0
    assert len(res["tool_results"]) == 1
    assert res["tool_results"][0]["tool"] == "run_command"


@pytest.mark.anyio
async def test_test_agent_failing_tests(mock_chat_service: MagicMock) -> None:
    registry = MagicMock(spec=ToolRegistry)
    registry.all_schemas.return_value = []
    
    router = MagicMock(spec=ToolRouter)
    mock_tool_res = MagicMock()
    mock_tool_res.success = False
    mock_tool_res.to_content.return_value = "Pytest failed: AssertionError"
    mock_tool_res.error = "AssertionError"
    router.dispatch.return_value = mock_tool_res

    agent = TestAgent(chat_service=mock_chat_service, tool_registry=registry, tool_router=router)

    # Tool call
    tc = ToolCall(
        id="tc-fail",
        function={"name": "run_command", "arguments": {"cmd": "pytest"}},
    )
    resp_tool = AIResponse(content="Running tests", tool_calls=[tc], finish_reason="tool_calls", model="mock-model")
    resp_stop = AIResponse(content="Done", tool_calls=[], finish_reason="stop", model="mock-model")
    mock_chat_service.chat_with_tools.side_effect = [resp_tool, resp_stop]

    # Report showing failures
    mock_report = {
        "passed": 2,
        "failed": 2,
        "skipped": 0,
        "errors": 0,
        "recommendations": ["Fix the divide by zero assertion in foo.py."]
    }
    mock_chat_service.provider.generate.return_value = AIResponse(
        content=json.dumps(mock_report), finish_reason="stop", model="mock-model"
    )

    state = {
        "goal": "Verify code",
        "created_artifacts": ["foo.py"],
        "tool_results": [],
        "messages": [],
        "agent_history": [],
        "agent_outputs": {},
        "agent_metrics": {},
    }

    res = await agent.run(state)
    assert res["test_report"].failed == 2
    assert "Fix the divide by zero" in res["test_report"].recommendations[0]


@pytest.mark.anyio
async def test_retrieval_testing_workflow_integration(mock_chat_service: MagicMock) -> None:
    planner_service = MagicMock()
    registry = MagicMock(spec=ToolRegistry)
    registry.all_schemas.return_value = []
    router = MagicMock(spec=ToolRouter)

    graph = build_agent_graph(
        chat_service=mock_chat_service,
        planner_service=planner_service,
        tool_registry=registry,
        tool_router=router,
        workspace_root="/tmp",
    ).compile()

    # Stub the mock responses so it goes from Planner to Retriever to Coder to Tester to Verifier to Reviewer
    # Planner response
    plan_text = json.dumps({
        "goal_summary": "Planner goal",
        "assumptions": [],
        "ordered_steps": [],
        "required_artifacts": [],
        "risks": [],
        "validation_checklist": [],
        "targets": []
    })
    
    # Retriever response
    retrieval_text = json.dumps({
        "retrieved_files": ["foo.py"],
        "summaries": {},
        "citations": {},
        "relevance_scores": {}
    })

    # Coder response
    coder_text = "Done implementing"

    # TestAgent response
    test_text = json.dumps({
        "passed": 3,
        "failed": 0,
        "skipped": 0,
        "errors": 0,
        "recommendations": []
    })

    # Reviewer response (approved)
    reviewer_text = json.dumps({
        "approved": True,
        "feedback": None,
        "route_to": None,
        "bugs": [],
        "risks": []
    })

    # Mock chat service generation outputs in order
    mock_chat_service.provider.generate.side_effect = [
        AIResponse(content=plan_text, finish_reason="stop", model="mock-model"),      # Planner
        AIResponse(content=retrieval_text, finish_reason="stop", model="mock-model"), # Retriever
        AIResponse(content=test_text, finish_reason="stop", model="mock-model"),      # TestAgent report
        AIResponse(content=reviewer_text, finish_reason="stop", model="mock-model"),  # Reviewer
        AIResponse(content="Final synthesis response", finish_reason="stop", model="mock-model"), # FinalResponse
    ]

    # Coder uses chat_with_tools
    mock_chat_service.chat_with_tools.side_effect = [
        AIResponse(content=coder_text, tool_calls=[], finish_reason="stop", model="mock-model"), # Coder loop stop
        AIResponse(content="Tester loop done", tool_calls=[], finish_reason="stop", model="mock-model"), # Tester tool loop stop
    ]

    # Patch verifier & RAG calls so we don't hit real workspace filesystem
    with patch("nakama_kun.agents.verifier.VerificationLayer.run") as mock_ver_run, \
         patch("nakama_kun.agents.retriever.get_retriever") as mock_get_ret:

        mock_report = MagicMock()
        mock_report.files_created = []
        mock_report.files_modified = []
        mock_report.command_results = []
        mock_report.summary = "Verification ok"
        mock_report.to_reviewer_text.return_value = "Mock verification report"
        mock_ver_run.return_value = mock_report

        mock_ret = MagicMock()
        mock_ret.retrieve.return_value = []
        mock_get_ret.return_value = mock_ret

        initial_state = {
            "goal": "Implement feature with tests",
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
        }

        res = await graph.ainvoke(initial_state)
        assert res["status"] == "done"
        assert res["active_agent"] == "ReviewerAgent"
        assert res["final_response"] == "Final synthesis response"
        assert "RetrieverAgent" in res["agent_outputs"]
        assert "TestAgent" in res["agent_outputs"]
