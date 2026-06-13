from __future__ import annotations

import json
from typing import Any

from loguru import logger

from nakama_kun.agents.base import BaseAgent
from nakama_kun.agents.prompts import PLANNER_AGENT_PROMPT
from nakama_kun.ai.models.message import Message
from nakama_kun.ai.models.plan import parse_plan
from nakama_kun.rag import get_retriever
from nakama_kun.workspace.context import WorkspaceContextBuilder


class PlannerAgent(BaseAgent):
    """Planner Agent decomposes goals into discrete tasks and file targets."""

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        logger.info("[PlannerAgent] Starting planning task...")
        goal = state.get("goal", "")
        feedback = state.get("reviewer_feedback")
        retry_count = state.get("retry_count", 0)

        # 1. Retrieve codebase context (RAG) and workspace summary
        workspace_context = ""
        try:
            workspace_context = WorkspaceContextBuilder().build_summary(goal)
        except Exception as e:
            logger.warning(f"Failed to build workspace context summary: {e}")

        rag_context = ""
        retriever = get_retriever()
        if retriever is not None:
            try:
                rag_context = retriever.retrieve_formatted_context(goal)
            except Exception as e:
                logger.warning(f"Failed to retrieve RAG context: {e}")

        # Build full system prompt
        system_prompt = PLANNER_AGENT_PROMPT
        if workspace_context:
            system_prompt += f"\n\n### Workspace Context\n{workspace_context}"
        if rag_context:
            system_prompt += f"\n\n### Retrieved Codebase Context\n{rag_context}"

        # 2. Build user prompt/refinement context
        if feedback:
            logger.info(f"[PlannerAgent] Refining plan based on reviewer feedback (retry {retry_count})...")

            # Extract completed and failed actions
            completed_actions = []
            previous_failures = []
            for r in state.get("tool_results", []):
                tool_name = r.get("tool", "")
                arguments = r.get("arguments", {})
                success = r.get("success", False)
                if success:
                    completed_actions.append(f"- Tool '{tool_name}' succeeded with args: {json.dumps(arguments)}")
                else:
                    error = r.get("error") or r.get("content") or "unknown error"
                    content_snippet = error[:200] + "..." if len(error) > 200 else error
                    previous_failures.append(
                        f"- Tool '{tool_name}' failed with args: {json.dumps(arguments)}\n"
                        f"  Output/Error: {content_snippet}"
                    )

            refinement_prompt = [
                "Your previous plan failed to meet requirements. Please refine it.",
                f"Original Goal: {goal}",
                f"Reviewer Feedback: {feedback}",
                "\n### Execution History",
                "Completed Actions:",
                "\n".join(completed_actions) if completed_actions else "(none)",
                "\nPrevious Failures:",
                "\n".join(previous_failures) if previous_failures else "(none)",
                "\nPlease refine the plan to address the feedback and failures."
            ]
            user_prompt = "\n".join(refinement_prompt)
        else:
            user_prompt = f"Goal: {goal}"

        # 3. Call LLM
        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt)
        ]
        response = await self.chat_service.provider.generate(messages)
        raw_text = response.content or ""

        # 4. Parse Plan
        plan = parse_plan(raw_text)

        # 5. Log decisions and append history
        thought = f"Decomposed goal. Success: {plan is not None}."
        if feedback:
            thought = f"Refined plan based on feedback. Success: {plan is not None}."

        log_entry = {
            "agent": "PlannerAgent",
            "thought": thought,
            "handoff": plan.model_dump() if plan else {"raw_response": raw_text},
        }

        history = list(state.get("agent_history", []))
        history.append(log_entry)

        # Prepare outputs matching make_planner_node expectations
        planned_artifacts = plan.required_artifacts if plan else []
        required_artifacts = planned_artifacts or state.get("required_artifacts", [])
        created_artifacts = list(state.get("created_artifacts", [])) if feedback else []
        missing_artifacts = [a for a in required_artifacts if a not in created_artifacts]

        return {
            "plan": plan,
            "required_artifacts": required_artifacts,
            "created_artifacts": created_artifacts,
            "missing_artifacts": missing_artifacts,
            "agent_history": history,
            "status": "executing",
            "messages": [
                Message(role="assistant", content=f"Planner proposed Plan:\n{raw_text}")
            ],
        }
