from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from loguru import logger

from nakama_kun.ai.models.message import Message
from nakama_kun.ai.prompts.system_prompt import (
    AGENT_SYSTEM_PROMPT,
)
from nakama_kun.ai.services.chat_service import ChatService
from nakama_kun.ai.services.planner_service import PlannerService
from nakama_kun.orchestration.state import AgentState
from nakama_kun.tools import ToolRegistry, ToolRouter


def make_planner_node(planner_service: PlannerService) -> Callable[[AgentState], Any]:
    """Factory creating the Planner Node.

    Planner node generates or refines the plan based on user goal and reviewer feedback.
    """

    async def planner_node(state: AgentState) -> dict[str, Any]:
        logger.info("[LangGraph] Planner Node starting...")
        goal = state["goal"]
        feedback = state["reviewer_feedback"]
        retry_count = state["retry_count"]

        # If there is feedback, ask the planner to refine the plan
        if feedback:
            logger.info(f"[LangGraph] Refining plan based on feedback (retry {retry_count})...")
            prompt = (
                f"Original Goal: {goal}\n\n"
                f"We previously attempted this, but a reviewer rejected it with this feedback:\n"
                f"{feedback}\n\n"
                f"Please update and refine the implementation plan to address this feedback."
            )
            # Increment retry count
            retry_count += 1
        else:
            logger.info("[LangGraph] Generating initial implementation plan...")
            prompt = goal

        plan, raw_text = await planner_service.plan(prompt)

        return {
            "plan": plan,
            "status": "executing",
            "retry_count": retry_count,
            "messages": [
                Message(role="assistant", content=f"Planner proposed Plan:\n{raw_text}")
            ],
        }

    return planner_node


def make_executor_node(
    chat_service: ChatService,
    tool_registry: ToolRegistry,
    tool_router: ToolRouter,
) -> Callable[[AgentState], Any]:
    """Factory creating the Executor Node.

    Executor node runs the tool-calling loop based on the current plan and goal.
    """

    async def executor_node(state: AgentState) -> dict[str, Any]:
        logger.info("[LangGraph] Executor Node starting...")
        goal = state["goal"]
        plan = state["plan"]
        plan_desc = plan.goal_summary if plan else "Execute target goal."

        # Setup system prompt with plan context
        system_prompt = (
            f"{AGENT_SYSTEM_PROMPT}\n\n"
            f"### Active Goal\n{goal}\n\n"
            f"### Active Plan\n{plan_desc}\n"
        )
        if plan and plan.ordered_steps:
            steps_str = "\n".join(f"{i}. {s}" for i, s in enumerate(plan.ordered_steps, 1))
            system_prompt += f"\n### Planned Steps:\n{steps_str}\n"

        tool_schemas = tool_registry.all_schemas()

        # Gather messages for LLM context: System message + user goal + current run messages
        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=f"Execute this task: {goal}"),
            *state["messages"],
        ]

        logger.info(f"[LangGraph] Calling LLM with {len(messages)} messages...")

        # Run up to 10 rounds of tool calling per executor invocation
        max_rounds = 10
        new_messages: list[Message] = []
        new_tool_results: list[dict[str, Any]] = []

        for round_idx in range(1, max_rounds + 1):
            logger.info(f"[LangGraph] Executor Round {round_idx}/{max_rounds}...")
            response = await chat_service.chat_with_tools(
                messages + new_messages, tool_schemas
            )

            # Check if execution finished
            if response.finish_reason == "stop" or not response.tool_calls:
                assistant_msg = Message(
                    role="assistant", content=response.content or ""
                )
                new_messages.append(assistant_msg)
                logger.info("[LangGraph] Execution completed.")
                break

            # Process tool calls
            assistant_msg = Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            )
            new_messages.append(assistant_msg)

            for tc in response.tool_calls:
                name = tc.function.get("name", "")
                arguments = tc.function.get("arguments", {})

                logger.info(f"[LangGraph] Dispatching tool {name} with args: {arguments}")
                try:
                    result = tool_router.dispatch(name, arguments)
                    success = result.success
                    content = result.to_content()
                except Exception as exc:
                    logger.error(f"[LangGraph] Tool execution failed: {exc}")
                    success = False
                    content = f"ERROR: {exc}"

                tool_result_msg = Message(
                    role="tool",
                    content=content,
                    tool_call_id=tc.id,
                    name=name,
                )
                new_messages.append(tool_result_msg)

                new_tool_results.append(
                    {
                        "tool": name,
                        "arguments": arguments,
                        "success": success,
                        "content": content,
                    }
                )

        return {
            "messages": new_messages,
            "tool_results": new_tool_results,
            "status": "reviewing",
        }

    return executor_node


def make_reviewer_node(chat_service: ChatService) -> Callable[[AgentState], Any]:
    """Factory creating the Reviewer Node.

    Reviewer node inspects the execution log and decides if the goal was met.
    """

    async def reviewer_node(state: AgentState) -> dict[str, Any]:
        logger.info("[LangGraph] Reviewer Node starting...")
        goal = state["goal"]
        plan = state["plan"]
        tool_results = state["tool_results"]

        plan_str = plan.goal_summary if plan else "None"
        results_summary = json.dumps(
            [
                {
                    "tool": r["tool"],
                    "success": r["success"],
                    "output_chars": len(r["content"]),
                }
                for r in tool_results
            ]
        )

        review_prompt = (
            f"You are a strict quality control reviewer.\n"
            f"Assess if the original goal has been fully met by the tool outputs.\n\n"
            f"Original Goal: {goal}\n"
            f"Proposed Plan: {plan_str}\n"
            f"Executed Tools Summary: {results_summary}\n\n"
            f"Please respond exactly in this format:\n"
            f"If approved:\n"
            f"[APPROVED]\n"
            f"<Brief approval summary>\n\n"
            f"If rejected (missing features, syntax errors, test failures):\n"
            f"[REJECTED]\n"
            f"<Explain what is missing or failed in a detailed bulleted list>"
        )

        messages = [
            Message(role="system", content="You are a strict QA reviewer agent."),
            Message(role="user", content=review_prompt),
        ]

        response = await chat_service.provider.generate(messages)
        content = response.content or ""
        logger.info(f"[LangGraph] Review response received:\n{content}")

        if "[APPROVED]" in content:
            logger.info("[LangGraph] QA Review: APPROVED.")
            return {
                "reviewer_feedback": None,
                "status": "done",
                "messages": [Message(role="assistant", content=f"Reviewer: Approved! {content}")],
            }
        else:
            logger.info("[LangGraph] QA Review: REJECTED.")
            return {
                "reviewer_feedback": content,
                "status": "planning",
                "messages": [Message(role="assistant", content=f"Reviewer: Rejected. {content}")],
            }

    return reviewer_node


def make_final_response_node(chat_service: ChatService) -> Callable[[AgentState], Any]:
    """Factory creating the Final Response Node.

    Synthesizes the plan execution and outputs a friendly markdown summary.
    """

    async def final_response_node(state: AgentState) -> dict[str, Any]:
        logger.info("[LangGraph] Final Response Node starting...")
        goal = state["goal"]
        plan = state["plan"]
        tool_results = state["tool_results"]

        summary_prompt = (
            f"Synthesize a final report summarizing the agent's work.\n"
            f"User Goal: {goal}\n"
            f"Plan Proposed: {plan.goal_summary if plan else 'None'}\n"
            f"Tool Executions: {len(tool_results)} runs.\n\n"
            f"Create a beautiful markdown summary reporting what actions were completed, "
            f"what files were modified or created, and confirming task completion."
        )

        messages = [
            Message(role="system", content="You are a helpful assistant reporting task results."),
            Message(role="user", content=summary_prompt),
        ]

        response = await chat_service.provider.generate(messages)
        content = response.content or ""

        return {"final_response": content, "status": "done"}

    return final_response_node
