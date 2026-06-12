from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from loguru import logger

from nakama_kun.ai.services.chat_service import ChatService
from nakama_kun.ai.services.planner_service import PlannerService
from nakama_kun.orchestration.nodes import (
    make_executor_node,
    make_final_response_node,
    make_planner_node,
    make_reviewer_node,
)
from nakama_kun.orchestration.state import AgentState
from nakama_kun.tools import ToolRegistry, ToolRouter


def route_after_review(state: AgentState) -> str:
    """Determine the next node to route to based on QA review feedback and retries."""
    feedback = state.get("reviewer_feedback")
    retry_count = state.get("retry_count", 0)

    if feedback is None:
        logger.info("[LangGraph] QA approved. Routing to final response.")
        return "final_response"

    # Limit retries to 3 attempts to prevent infinite agent loops
    if retry_count >= 3:
        logger.warning(
            f"[LangGraph] QA rejected but retry limit ({retry_count}/3) reached. "
            f"Routing to final response with failure state."
        )
        return "final_response"

    logger.info(
        f"[LangGraph] QA rejected. Routing back to Planner Node (Retry {retry_count + 1}/3)."
    )
    return "planner"


def build_agent_graph(
    chat_service: ChatService,
    planner_service: PlannerService,
    tool_registry: ToolRegistry,
    tool_router: ToolRouter,
) -> Any:
    """Build and return compiled StateGraph workflow for Agent execution."""
    workflow = StateGraph(AgentState)

    # 1. Create nodes
    planner_node: Any = make_planner_node(planner_service)
    executor_node: Any = make_executor_node(chat_service, tool_registry, tool_router)
    reviewer_node: Any = make_reviewer_node(chat_service)
    final_response_node: Any = make_final_response_node(chat_service)

    # 2. Add nodes to graph
    workflow.add_node("planner", planner_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("reviewer", reviewer_node)
    workflow.add_node("final_response", final_response_node)

    # 3. Define transitions / edges
    workflow.add_edge(START, "planner")
    workflow.add_edge("planner", "executor")
    workflow.add_edge("executor", "reviewer")

    # Conditional routing after QA Review
    workflow.add_conditional_edges(
        "reviewer",
        route_after_review,
        {
            "planner": "planner",
            "final_response": "final_response",
        },
    )

    workflow.add_edge("final_response", END)

    return workflow
