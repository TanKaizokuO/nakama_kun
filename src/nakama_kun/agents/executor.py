from __future__ import annotations

from typing import Any

from loguru import logger

from nakama_kun.agents.base import BaseAgent
from nakama_kun.agents.prompts import EXECUTOR_AGENT_PROMPT
from nakama_kun.ai.models.message import Message
from nakama_kun.ai.services.chat_service import ChatService
from nakama_kun.orchestration.goal_satisfaction import check_goal_satisfaction
from nakama_kun.orchestration.nodes import (
    DELIVERY_TOOLS,
    EXPLORATION_TOOLS,
    RESEARCH_THRESHOLD,
    _action_signature,
    _build_attempt_history,
    _count_research_actions,
    _delivery_guidance,
    _extract_tool_error,
    _missing_required_artifacts,
    _prioritize_tool_schemas,
    _render_tool_observation,
    _tool_call_key,
)
from nakama_kun.tools import ToolRegistry, ToolResult, ToolRouter


class ExecutorAgent(BaseAgent):
    """Executor Agent runs tool-calling loops to apply coder proposals and run tests."""

    def __init__(
        self,
        chat_service: ChatService,
        tool_registry: ToolRegistry,
        tool_router: ToolRouter,
    ) -> None:
        from nakama_kun.agents.prompts import EXECUTOR_AGENT_PROMPT
        super().__init__(
            name="ExecutorAgent",
            role="coder",
            system_prompt=EXECUTOR_AGENT_PROMPT,
            chat_service=chat_service,
            tools=tool_registry.all_schemas() if tool_registry else [],
        )
        self.tool_registry = tool_registry
        self.tool_router = tool_router

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        logger.info("[ExecutorAgent] Starting execution task...")
        goal = state["goal"]
        plan = state.get("plan")
        plan_desc = plan.goal_summary if plan else "Execute target goal."
        
        goal_satisfied = state.get("goal_satisfied", False)
        task_type = state.get("task_type") or "MODIFICATION"

        if goal_satisfied:
            logger.info("[ExecutorAgent] Goal is already satisfied. Skipping execution.")
            return {
                "messages": [],
                "tool_results": [],
                "created_artifacts": list(state.get("created_artifacts", [])),
                "research_budget_remaining": state.get("research_budget_remaining", 15),
                "delivery_mode": state.get("delivery_mode", False),
                "agent_history": list(state.get("agent_history", [])),
                "status": "reviewing",
                "goal_satisfied": True,
            }

        # 1. Setup system prompt including coder proposals
        system_prompt = (
            f"{EXECUTOR_AGENT_PROMPT}\n\n"
            f"### Active Goal\n{goal}\n\n"
            f"### Active Plan\n{plan_desc}\n"
        )
        if plan and plan.ordered_steps:
            steps_str = "\n".join(f"{i}. {s}" for i, s in enumerate(plan.ordered_steps, 1))
            system_prompt += f"\n### Planned Steps:\n{steps_str}\n"

        proposals = state.get("coder_proposals", [])
        if proposals:
            system_prompt += "\n### Coder Agent Proposed Changes:\n"
            for p in proposals:
                system_prompt += (
                    f"  - File: {p.get('path')}\n"
                    f"    Explanation: {p.get('explanation')}\n"
                    f"    Proposed Content:\n---\n{p.get('content')}\n---\n\n"
                )

        tool_schemas = self.tool_registry.all_schemas()

        # Gather messages for LLM context
        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=f"Execute this task: {goal}"),
            *state["messages"],
        ]

        max_rounds = 10
        new_messages: list[Message] = []
        new_tool_results: list[dict[str, Any]] = []
        attempt_history = _build_attempt_history(state.get("tool_results", []))

        required_artifacts = state.get("required_artifacts", [])
        created_artifacts = list(state.get("created_artifacts", []))
        missing_artifacts = _missing_required_artifacts(required_artifacts, created_artifacts)
        research_actions_used = _count_research_actions(state.get("tool_results", []))
        research_budget_remaining = state.get(
            "research_budget_remaining",
            max(RESEARCH_THRESHOLD - research_actions_used, 0),
        )
        delivery_mode = state.get("delivery_mode", False)
        failed_attempt_signatures = set(
            (state.get("retry_memory") or {}).get("failed_attempt_signatures", [])
        )

        early_stop_telemetry = state.get("early_stop_telemetry")

        round_idx = 1
        for round_idx in range(1, max_rounds + 1):
            if goal_satisfied:
                break
            logger.info(f"[ExecutorAgent] Executor Round {round_idx}/{max_rounds}...")

            missing_artifacts = _missing_required_artifacts(required_artifacts, created_artifacts)
            if missing_artifacts and (
                research_budget_remaining <= 0
                or research_actions_used >= RESEARCH_THRESHOLD
                or round_idx >= max_rounds - 2
            ):
                delivery_mode = True

            current_messages = messages + new_messages

            if missing_artifacts and delivery_mode:
                current_messages.append(_delivery_guidance(missing_artifacts))
            elif missing_artifacts:
                current_messages.append(
                    Message(
                        role="system",
                        content=(
                            f"Missing required artifacts: {missing_artifacts}. "
                            f"Research budget remaining: {research_budget_remaining}. "
                            "You must create them to complete the task."
                        ),
                    )
                )

            response = await self.chat_service.chat_with_tools(
                current_messages, _prioritize_tool_schemas(tool_schemas, delivery_mode)
            )

            # Check if execution finished
            if response.finish_reason == "stop" or not response.tool_calls:
                assistant_msg = Message(
                    role="assistant", content=response.content or ""
                )
                new_messages.append(assistant_msg)
                if missing_artifacts and not delivery_mode:
                    delivery_mode = True
                    logger.info("[ExecutorAgent] LLM stopped before required artifacts; forcing delivery mode.")
                    continue
                logger.info("[ExecutorAgent] Execution completed.")
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

                # Tool Selection Layer Optimization
                from nakama_kun.tools.selection import ToolSelectionLayer
                selection = ToolSelectionLayer(new_tool_results + state.get("tool_results", []))
                final_name, final_arguments, block_reason = selection.filter_and_optimize(name, arguments)

                key = _tool_call_key(final_name, final_arguments)
                previous_attempt = attempt_history.get(key)
                signature = _action_signature(final_name, final_arguments)

                logger.info(f"[ExecutorAgent] Dispatching tool {final_name} with args: {final_arguments}")
                error: str | None = None

                if block_reason:
                    error = block_reason
                    result = ToolResult(success=False, error=error)
                    success = result.success
                    content = result.to_content()
                    logger.warning(f"[ExecutorAgent] ToolSelectionLayer blocked: {block_reason}")
                elif delivery_mode and missing_artifacts and final_name in EXPLORATION_TOOLS:
                    error = (
                        f"BUDGET EXHAUSTED: RESEARCH PHASE COMPLETE. Tool '{final_name}' is blocked. "
                        "Further repository exploration is prohibited unless explicitly justified. "
                        f"Create the missing artifacts now: {missing_artifacts}. Preferred tool: write_file."
                    )
                    result = ToolResult(success=False, error=error)
                    success = result.success
                    content = result.to_content()
                    logger.warning(
                        f"[ExecutorAgent] Blocked exploratory tool call {final_name} in delivery mode."
                    )
                elif (
                    previous_attempt and previous_attempt.get("last_result") is False
                ) or signature in failed_attempt_signatures:
                    error = (
                        "Identical tool call already failed. "
                        "WARNING: This action already failed. Choose a different strategy."
                    )
                    result = ToolResult(success=False, error=error)
                    success = result.success
                    content = result.to_content()
                    attempt_num = (previous_attempt["attempt_count"] if previous_attempt else 0) + 1
                    logger.warning(
                        f"[ExecutorAgent] Blocked repeated failed tool call {final_name} "
                        f"attempt={attempt_num}"
                    )
                else:
                    try:
                        result = await self.tool_router.dispatch(final_name, final_arguments, task_type=task_type)
                        success = result.success
                        content = result.to_content()
                    except Exception as exc:
                        logger.error(f"[ExecutorAgent] Tool execution failed: {exc}")
                        result = ToolResult(success=False, error=str(exc))
                        success = False
                        content = result.to_content()

                error = _extract_tool_error(result, content) if not success else None
                observation = _render_tool_observation(final_name, success, content, error)
                attempt_count = (previous_attempt["attempt_count"] if previous_attempt else 0) + 1
                attempt_history[key] = {
                    "attempt_count": attempt_count,
                    "last_result": success,
                    "last_error": error,
                }
                if not success:
                    failed_attempt_signatures.add(signature)

                tool_result_msg = Message(
                    role="tool",
                    content=observation,
                    tool_call_id=tc.id,
                    name=final_name,
                )
                new_messages.append(tool_result_msg)

                # Record tool results
                new_tool_results.append(
                    {
                        "tool": final_name,
                        "arguments": final_arguments,
                        "success": success,
                        "content": content,
                        "error": error,
                    }
                )

                if success and not goal_satisfied:
                    gsr = check_goal_satisfaction(
                        task=goal,
                        task_type=task_type,
                        tool_outputs=new_tool_results,
                        evidence_store=state.get("evidence_store"),
                        execution_history=state.get("agent_history", []),
                    )
                    if gsr.goal_satisfied:
                        goal_satisfied = True
                        early_stop_telemetry = {
                            "stop_reason": gsr.explanation,
                            "stop_round": round_idx,
                            "evidence_used": new_tool_results[-1] if new_tool_results else None,
                        }
                        logger.info(
                            f"[ExecutorAgent] GoalSatisfactionDetector: {gsr.explanation} "
                            f"(confidence={gsr.confidence:.2f})"
                        )

                if goal_satisfied:
                    break

                if final_name in EXPLORATION_TOOLS:
                    research_actions_used += 1
                    research_budget_remaining = max(RESEARCH_THRESHOLD - research_actions_used, 0)
                elif final_name in DELIVERY_TOOLS:
                    # Parse path from output to track created artifacts
                    from nakama_kun.orchestration.verification import (
                        _extract_path_from_write_output,
                    )
                    written_path = _extract_path_from_write_output(content)
                    if not written_path and isinstance(final_arguments, dict) and "path" in final_arguments:
                        written_path = final_arguments["path"]
                    if written_path:
                        import os
                        from pathlib import Path
                        try:
                            abs_path = Path(written_path) if Path(written_path).is_absolute() else Path(os.getcwd()) / written_path
                            rel_path = str(abs_path.resolve().relative_to(Path(os.getcwd()).resolve()))
                            if rel_path not in created_artifacts:
                                created_artifacts.append(rel_path)
                        except Exception:
                            if written_path not in created_artifacts:
                                created_artifacts.append(written_path)

            if goal_satisfied:
                logger.info("[ExecutorAgent] Goal satisfied. Terminating execution early.")
                break

        # 5. Log decisions to agent_history
        thought = f"Executed {len(new_tool_results)} tool actions."
        log_entry = {
            "agent": "ExecutorAgent",
            "thought": thought,
            "handoff": {
                "rounds": round_idx,
                "created_artifacts": created_artifacts,
                "tool_results_count": len(new_tool_results)
            }
        }
        history = list(state.get("agent_history", []))
        history.append(log_entry)

        return {
            "messages": new_messages,
            "tool_results": new_tool_results,
            "created_artifacts": created_artifacts,
            "research_budget_remaining": research_budget_remaining,
            "delivery_mode": delivery_mode,
            "agent_history": history,
            "status": "reviewing",
            "goal_satisfied": goal_satisfied,
            "early_stop_telemetry": early_stop_telemetry,
        }
