from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from nakama_kun.ai.models.message import Message
from nakama_kun.ai.models.response import AIResponse, TokenUsage
from nakama_kun.orchestration.task_classifier import TASK_TYPE_RETRIEVAL
from nakama_kun.agents.reviewer import ReviewerAgent, CODE_REVIEW_PROMPT, RETRIEVAL_REVIEW_PROMPT


def _make_ai_response(content: str) -> AIResponse:
    return AIResponse(
        content=content,
        model="test-reviewer-model",
        usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        finish_reason="stop",
        latency=0.1,
    )


@pytest.mark.anyio
async def test_reviewer_refactor_directory_listing() -> None:
    # 1. Directory Listing (Retrieval Review Mode)
    # GIVEN: task_type == RETRIEVAL, goal_satisfied == True
    # EXPECT: system prompt should be RETRIEVAL_REVIEW_PROMPT
    mock_response = _make_ai_response('{"approved": true, "feedback": null, "route_to": null, "bugs": [], "risks": []}')
    mock_provider = MagicMock()
    mock_provider.generate = AsyncMock(return_value=mock_response)
    
    chat_service = MagicMock()
    chat_service.provider = mock_provider

    agent = ReviewerAgent(chat_service)
    state = {
        "goal": "List files in directory",
        "task_type": TASK_TYPE_RETRIEVAL,
        "goal_satisfied": True,
        "verification_report": None,
        "agent_history": [],
    }

    res = await agent.run(state)

    # Verify generate was called with RETRIEVAL_REVIEW_PROMPT
    assert mock_provider.generate.called
    call_args = mock_provider.generate.call_args[0][0]
    # first message is system
    assert call_args[0].role == "system"
    assert call_args[0].content == RETRIEVAL_REVIEW_PROMPT
    
    assert res["status"] == "done"
    assert res["reviewer_feedback"] is None


@pytest.mark.anyio
async def test_reviewer_refactor_pdf_explanation() -> None:
    # 2. PDF Explanation (Retrieval Review Mode)
    # GIVEN: task_type == RETRIEVAL, goal_satisfied == True
    # EXPECT: system prompt should be RETRIEVAL_REVIEW_PROMPT
    mock_response = _make_ai_response('{"approved": true, "feedback": null, "route_to": null, "bugs": [], "risks": []}')
    mock_provider = MagicMock()
    mock_provider.generate = AsyncMock(return_value=mock_response)
    
    chat_service = MagicMock()
    chat_service.provider = mock_provider

    agent = ReviewerAgent(chat_service)
    state = {
        "goal": "Explain content of manual.pdf",
        "task_type": TASK_TYPE_RETRIEVAL,
        "goal_satisfied": True,
        "verification_report": None,
        "agent_history": [],
    }

    res = await agent.run(state)
    assert mock_provider.generate.called
    call_args = mock_provider.generate.call_args[0][0]
    assert call_args[0].content == RETRIEVAL_REVIEW_PROMPT
    assert res["status"] == "done"


@pytest.mark.anyio
async def test_reviewer_refactor_file_reading() -> None:
    # 3. File Reading (Retrieval Review Mode)
    # GIVEN: task_type == RETRIEVAL, goal_satisfied == True
    # EXPECT: system prompt should be RETRIEVAL_REVIEW_PROMPT
    mock_response = _make_ai_response('{"approved": true, "feedback": null, "route_to": null, "bugs": [], "risks": []}')
    mock_provider = MagicMock()
    mock_provider.generate = AsyncMock(return_value=mock_response)
    
    chat_service = MagicMock()
    chat_service.provider = mock_provider

    agent = ReviewerAgent(chat_service)
    state = {
        "goal": "Read database configuration file",
        "task_type": TASK_TYPE_RETRIEVAL,
        "goal_satisfied": True,
        "verification_report": None,
        "agent_history": [],
    }

    res = await agent.run(state)
    assert mock_provider.generate.called
    call_args = mock_provider.generate.call_args[0][0]
    assert call_args[0].content == RETRIEVAL_REVIEW_PROMPT
    assert res["status"] == "done"


@pytest.mark.anyio
async def test_reviewer_refactor_version_query() -> None:
    # 4. Version Query (Retrieval Review Mode)
    # GIVEN: task_type == RETRIEVAL, goal_satisfied == True
    # EXPECT: system prompt should be RETRIEVAL_REVIEW_PROMPT
    mock_response = _make_ai_response('{"approved": true, "feedback": null, "route_to": null, "bugs": [], "risks": []}')
    mock_provider = MagicMock()
    mock_provider.generate = AsyncMock(return_value=mock_response)
    
    chat_service = MagicMock()
    chat_service.provider = mock_provider

    agent = ReviewerAgent(chat_service)
    state = {
        "goal": "Check python version",
        "task_type": TASK_TYPE_RETRIEVAL,
        "goal_satisfied": True,
        "verification_report": None,
        "agent_history": [],
    }

    res = await agent.run(state)
    assert mock_provider.generate.called
    call_args = mock_provider.generate.call_args[0][0]
    assert call_args[0].content == RETRIEVAL_REVIEW_PROMPT
    assert res["status"] == "done"


@pytest.mark.anyio
async def test_reviewer_refactor_code_modification() -> None:
    # 5. Code Modification (Code Review Mode)
    # GIVEN: task_type == CODE_MODIFICATION (or default)
    # EXPECT: system prompt should be CODE_REVIEW_PROMPT
    mock_response = _make_ai_response('{"approved": true, "feedback": null, "route_to": null, "bugs": [], "risks": []}')
    mock_provider = MagicMock()
    mock_provider.generate = AsyncMock(return_value=mock_response)
    
    chat_service = MagicMock()
    chat_service.provider = mock_provider

    agent = ReviewerAgent(chat_service)
    state = {
        "goal": "Implement auth validation",
        "task_type": "CODE_MODIFICATION",
        "goal_satisfied": False,
        "verification_report": None,
        "agent_history": [],
    }

    res = await agent.run(state)
    assert mock_provider.generate.called
    call_args = mock_provider.generate.call_args[0][0]
    assert call_args[0].content == CODE_REVIEW_PROMPT
    assert res["status"] == "done"
