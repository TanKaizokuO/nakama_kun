from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from nakama_kun.orchestration.state import AgentState
from nakama_kun.orchestration.task_classifier import TASK_TYPE_RETRIEVAL
from nakama_kun.orchestration.workflow import route_after_review


def test_retry_routing_successful_retrieval() -> None:
    # Under a successful retrieval task, goal_satisfied is True.
    # Even if there's reviewer feedback (rejection), route_after_review must bypass retries and route directly to final_response.
    state: AgentState = {
        "goal": "List contents of project",
        "task_type": TASK_TYPE_RETRIEVAL,
        "tool_results": [{"tool": "list_files", "success": True, "content": "file.txt"}],
        "evidence_store": None,
        "agent_history": [],
        "reviewer_feedback": "Please retry, something is missing",
        "retry_count": 0,
        "goal_satisfied": True,
        "reviewer_route": "planner",
    }

    next_node = route_after_review(state)
    assert next_node == "final_response"


def test_retry_routing_failed_retrieval() -> None:
    # Under a failed/unsatisfied retrieval task, goal_satisfied is False.
    # If reviewer rejects (feedback present) and retry limit is not reached, retries should be allowed (routes back to planner or coder).
    state: AgentState = {
        "goal": "List contents of project",
        "task_type": TASK_TYPE_RETRIEVAL,
        "tool_results": [{"tool": "list_files", "success": False, "content": "Permission denied"}],
        "evidence_store": None,
        "agent_history": [],
        "reviewer_feedback": "Goal unsatisfied, listing failed.",
        "retry_count": 0,
        "goal_satisfied": False,
        "reviewer_route": "planner",
    }

    next_node = route_after_review(state)
    assert next_node == "planner"

    # Increment retry_count to the limit (3)
    state["retry_count"] = 3
    next_node_limit = route_after_review(state)
    assert next_node_limit == "final_response"
