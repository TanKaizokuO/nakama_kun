import pytest
from nakama_kun.orchestration.state import AgentState
from nakama_kun.orchestration.nodes import make_executor_node, make_verifier_node, make_planner_node
from nakama_kun.ai.models.plan import Plan
from nakama_kun.tools.registry import ToolRegistry
from nakama_kun.tools.router import ToolRouter
from nakama_kun.ai.models.message import Message, ToolCall
from nakama_kun.ai.models.response import AIResponse
import asyncio

@pytest.fixture
def base_state() -> AgentState:
    return {
        "goal": "Test required artifacts",
        "plan": Plan(goal_summary="Test", ordered_steps=[], required_artifacts=["ARCHITECTURE.md"]),
        "required_artifacts": ["ARCHITECTURE.md"],
        "created_artifacts": [],
        "messages": [],
        "tool_results": [],
        "verification_report": None,
        "evidence_store": None,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "executing",
    }

class MockChatService:
    def __init__(self, responses):
        self.responses = responses
        self.call_count = 0
        
    async def chat_with_tools(self, messages, schemas):
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            return resp
        return AIResponse(content="Done.", finish_reason="stop", model="test")


@pytest.mark.asyncio
async def test_artifact_missing_after_execution(base_state, tmp_path):
    verifier_node = make_verifier_node(workspace_root=str(tmp_path))
    state = await verifier_node(base_state)
    report = state["verification_report"]
    signal = report.evaluate_outcome()
    
    assert signal.recommendation == "REJECT"
    assert "required artifact" in signal.reason.lower()
    assert "ARCHITECTURE.md" in signal.reason


@pytest.mark.asyncio
async def test_artifact_successfully_created(base_state, tmp_path):
    (tmp_path / "ARCHITECTURE.md").write_text("content")
    
    verifier_node = make_verifier_node(workspace_root=str(tmp_path))
    state = await verifier_node(base_state)
    report = state["verification_report"]
    signal = report.evaluate_outcome()
    
    assert signal.recommendation == "APPROVE"


@pytest.mark.asyncio
async def test_execution_budget_exhaustion(base_state):
    tc_read = ToolCall(
        id="call_1",
        type="function",
        function={"name": "list_files", "arguments": "{}"}
    )
    
    # 8 empty tool call responses to advance to round 8, then 1 read tool
    responses = [AIResponse(content="wait", finish_reason="tool_calls", tool_calls=[], model="test") for _ in range(7)]
    responses.append(AIResponse(content="reading", finish_reason="tool_calls", tool_calls=[tc_read], model="test"))
    responses.append(AIResponse(content="done", finish_reason="stop", model="test"))
    
    chat_service = MockChatService(responses)
    registry = ToolRegistry()
    router = ToolRouter(registry)
    executor_node = make_executor_node(chat_service, registry, router)
    
    state = await executor_node(base_state)
    
    tool_results = state["tool_results"]
    assert any(tr["tool"] == "list_files" and "BUDGET EXHAUSTED" in tr["error"] for tr in tool_results)
