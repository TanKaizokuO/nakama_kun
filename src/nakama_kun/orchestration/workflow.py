from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from loguru import logger

from nakama_kun.ai.services.chat_service import ChatService
from nakama_kun.ai.services.planner_service import PlannerService
from nakama_kun.orchestration.nodes import (
    make_coder_agent_node,
    make_final_response_node,
    make_planner_agent_node,
    make_reviewer_agent_node,
    make_verifier_agent_node,
    make_retriever_agent_node,
    make_test_agent_node,
    make_security_agent_node,
)
from nakama_kun.orchestration.state import AgentState
from nakama_kun.tools import ToolRegistry, ToolRouter


def route_after_review(state: AgentState) -> str:
    """Determine the next node to route to based on QA review feedback and retries."""
    from nakama_kun.orchestration.goal_satisfaction import check_goal_satisfaction
    
    goal = state.get("goal")
    task_type = state.get("task_type") or "MODIFICATION"
    tool_results = state.get("tool_results", [])
    evidence_store = state.get("evidence_store")
    agent_history = state.get("agent_history", [])
    
    gsr = check_goal_satisfaction(
        task=goal,
        task_type=task_type,
        tool_outputs=tool_results,
        evidence_store=evidence_store,
        execution_history=agent_history,
    )
    
    if gsr.goal_satisfied or state.get("goal_satisfied", False):
        logger.info("[LangGraph] Goal satisfied. Bypassing QA rejection / retry routing to final response.")
        return "final_response"

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

    route = state.get("reviewer_route") or "planner"
    if route not in ("planner", "coder"):
        route = "planner"

    logger.info(
        f"[LangGraph] QA rejected. Routing back to {route.capitalize()} Node (Retry {retry_count + 1}/3)."
    )
    
    if route == "planner":
        return "planner_agent_node"
    return "coder_agent_node"


def route_after_executor(state: AgentState) -> str:
    """Determine the next node to route to after the Executor."""
    if state.get("goal_satisfied", False):
        logger.info("[LangGraph] Goal satisfied early. Routing directly to final response.")
        return "final_response"
    return "verifier"


def route_after_coder(state: AgentState) -> str:
    """Determine the next node to route to after the Coder."""
    if state.get("goal_satisfied", False):
        logger.info("[LangGraph] Goal satisfied early. Routing directly to final response.")
        return "final_response"
    return "test_agent_node"


def build_agent_graph(
    chat_service: ChatService,
    planner_service: PlannerService,
    tool_registry: ToolRegistry,
    tool_router: ToolRouter,
    workspace_root: str | None = None,
) -> Any:
    """Build and return compiled StateGraph workflow for Agent execution."""
    workflow = StateGraph(AgentState)

    # 1. Create nodes
    planner_agent_node: Any = make_planner_agent_node(chat_service, tool_registry)
    retriever_agent_node: Any = make_retriever_agent_node(chat_service, workspace_root)
    coder_agent_node: Any = make_coder_agent_node(chat_service, tool_registry, tool_router)
    test_agent_node: Any = make_test_agent_node(chat_service, tool_registry, tool_router)
    security_agent_node: Any = make_security_agent_node(chat_service)
    verifier_agent_node: Any = make_verifier_agent_node(workspace_root, chat_service)
    reviewer_agent_node: Any = make_reviewer_agent_node(chat_service, workspace_root)
    final_response_node: Any = make_final_response_node(chat_service)

    # 2. Add nodes to graph
    workflow.add_node("planner_agent_node", planner_agent_node)
    workflow.add_node("retriever_agent_node", retriever_agent_node)
    workflow.add_node("coder_agent_node", coder_agent_node)
    workflow.add_node("test_agent_node", test_agent_node)
    workflow.add_node("security_agent_node", security_agent_node)
    workflow.add_node("verifier_agent_node", verifier_agent_node)
    workflow.add_node("reviewer_agent_node", reviewer_agent_node)
    workflow.add_node("final_response", final_response_node)

    # 3. Define transitions / edges
    workflow.add_edge(START, "planner_agent_node")
    workflow.add_edge("planner_agent_node", "retriever_agent_node")
    workflow.add_edge("retriever_agent_node", "coder_agent_node")
    
    # Conditional routing after Coder Agent
    workflow.add_conditional_edges(
        "coder_agent_node",
        route_after_coder,
        {
            "test_agent_node": "test_agent_node",
            "final_response": "final_response",
        },
    )
    
    workflow.add_edge("test_agent_node", "security_agent_node")
    workflow.add_edge("security_agent_node", "verifier_agent_node")
    workflow.add_edge("verifier_agent_node", "reviewer_agent_node")

    # Conditional routing after QA Review
    workflow.add_conditional_edges(
        "reviewer_agent_node",
        route_after_review,
        {
            "planner_agent_node": "planner_agent_node",
            "coder_agent_node": "coder_agent_node",
            "final_response": "final_response",
        },
    )

    workflow.add_edge("final_response", END)

    return workflow
