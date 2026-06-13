from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import pytest

from nakama_kun.ai.models.plan import Plan
from nakama_kun.ai.models.response import AIResponse
from nakama_kun.orchestration.evidence import EvidenceStore
from nakama_kun.orchestration.nodes import (
    make_final_response_node,
    _build_retrieval_evidence_block,
)
from nakama_kun.orchestration.state import AgentState
from nakama_kun.orchestration.task_classifier import TASK_TYPE_RETRIEVAL


def _make_mock_service(response_text: str = "LLM answer.") -> MagicMock:
    mock = MagicMock()
    mock.provider = MagicMock()
    llm_resp = MagicMock(spec=AIResponse)
    llm_resp.content = response_text
    mock.provider.generate = AsyncMock(return_value=llm_resp)
    return mock


def _base_state(**overrides) -> AgentState:  # type: ignore[return]
    state: AgentState = {  # type: ignore[assignment]
        "goal": "Explain Deepfake_Forensics.pdf",
        "plan": Plan(
            goal_summary="Explain pdf",
            targets=[],
            assumptions=[],
            ordered_steps=["Search PDF"],
            risks=[],
            validation_checklist=[],
        ),
        "messages": [],
        "tool_results": [],
        "verification_report": None,
        "evidence_store": None,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "reviewing",
        "task_type": TASK_TYPE_RETRIEVAL,
        "required_artifacts": [],
        "created_artifacts": [],
        "missing_artifacts": [],
        "research_budget_remaining": 15,
        "delivery_mode": False,
    }
    state.update(overrides)  # type: ignore[arg-type]
    return state


@pytest.mark.anyio
async def test_search_vector_store_surfaced_in_final_response() -> None:
    # GIVEN: A search_vector_store tool output containing PDF content
    store = EvidenceStore()
    store.add_tool_output(
        tool="search_vector_store",
        arguments={"query": "explain deepfakes"},
        success=True,
        output="Deepfake forensics dataset consists of face manipulation detection images.",
    )

    mock_service = _make_mock_service("According to the vector store: Deepfake forensics dataset...")
    node = make_final_response_node(mock_service)

    state = _base_state(
        goal="Explain Deepfake_Forensics.pdf",
        task_type=TASK_TYPE_RETRIEVAL,
        evidence_store=store,
    )

    result = await node(state)

    # 1. Assert prompt contains search_vector_store evidence content
    called_messages = mock_service.provider.generate.call_args[0][0]
    user_msg = next(m for m in called_messages if m.role == "user")
    prompt = user_msg.content

    assert "search_vector_store" in prompt
    assert "face manipulation detection" in prompt
    assert "RETRIEVED EVIDENCE" in prompt

    # 2. Result is generated and grounded
    assert result["status"] == "done"
    assert "Deepfake forensics" in result["final_response"]


@pytest.mark.anyio
async def test_search_vector_store_fallback_results_surfaced() -> None:
    # GIVEN: No EvidenceStore (terminated early), but raw tool_results has search_vector_store
    mock_service = _make_mock_service("Extracted PDF content info.")
    node = make_final_response_node(mock_service)

    state = _base_state(
        goal="Explain Deepfake_Forensics.pdf",
        task_type=TASK_TYPE_RETRIEVAL,
        evidence_store=None,
        tool_results=[
            {
                "tool": "search_vector_store",
                "success": True,
                "arguments": {"query": "explain deepfakes"},
                "content": "Deepfake forensics dataset contains 1000 video files.",
            }
        ],
    )

    result = await node(state)

    called_messages = mock_service.provider.generate.call_args[0][0]
    user_msg = next(m for m in called_messages if m.role == "user")
    prompt = user_msg.content

    assert "search_vector_store" in prompt
    assert "1000 video files" in prompt
    assert "RETRIEVED EVIDENCE" in prompt
    assert result["final_response"] == "Extracted PDF content info."
