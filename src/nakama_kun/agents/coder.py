from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger

from nakama_kun.agents.base import BaseAgent
from nakama_kun.agents.models import CoderHandoff
from nakama_kun.agents.prompts import CODER_AGENT_PROMPT
from nakama_kun.ai.models.message import Message
from nakama_kun.workspace.context import WorkspaceContextBuilder


def parse_coder_handoff(text: str) -> CoderHandoff | None:
    """Parse a structured CoderHandoff model from JSON text or code blocks."""
    text_stripped = text.strip()
    try:
        data = json.loads(text_stripped)
        return CoderHandoff.model_validate(data)
    except Exception:
        pass

    # Try matching json block ```json ... ```
    match = re.search(r"```json\s*(.*?)\s*```", text_stripped, re.DOTALL | re.IGNORECASE)
    if match:
        try:
            data = json.loads(match.group(1).strip())
            return CoderHandoff.model_validate(data)
        except Exception:
            pass

    # Try matching general block ``` ... ```
    match = re.search(r"```\s*(.*?)\s*```", text_stripped, re.DOTALL | re.IGNORECASE)
    if match:
        try:
            data = json.loads(match.group(1).strip())
            return CoderHandoff.model_validate(data)
        except Exception:
            pass

    return None


class CoderAgent(BaseAgent):
    """Coder Agent generates proposed code modifications based on the plan."""

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        logger.info("[CoderAgent] Starting coding task...")
        goal = state.get("goal", "")
        plan = state.get("plan")
        feedback = state.get("reviewer_feedback")

        plan_desc = plan.goal_summary if plan else "Execute target goal."

        # 1. Gather workspace context
        workspace_context = ""
        try:
            workspace_context = WorkspaceContextBuilder().build_summary()
        except Exception as e:
            logger.warning(f"Failed to build workspace context summary: {e}")

        # Build full system prompt
        system_prompt = CODER_AGENT_PROMPT
        if workspace_context:
            system_prompt += f"\n\n### Workspace Context\n{workspace_context}"

        # 2. Build user prompt
        user_prompt_lines = [
            f"Goal: {goal}",
            f"Active Plan goal summary: {plan_desc}",
        ]
        if plan and plan.ordered_steps:
            steps_str = "\n".join(f"{i}. {s}" for i, s in enumerate(plan.ordered_steps, 1))
            user_prompt_lines.append(f"\nPlanned Steps:\n{steps_str}")
        if plan and plan.required_artifacts:
            user_prompt_lines.append(f"\nRequired Artifacts: {plan.required_artifacts}")

        if feedback:
            user_prompt_lines.append(f"\nReviewer Feedback: {feedback}")

        # 3. Call LLM
        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content="\n".join(user_prompt_lines))
        ]
        response = await self.chat_service.provider.generate(messages)
        raw_text = response.content or ""

        # 4. Parse Handoff
        handoff = parse_coder_handoff(raw_text)

        # 5. Log decisions to agent_history
        proposals_dict = []
        if handoff:
            proposals_dict = [p.model_dump() for p in handoff.proposals]
            thought = f"Proposed {len(handoff.proposals)} file changes."
        else:
            thought = "Failed to generate structured proposals."

        log_entry = {
            "agent": "CoderAgent",
            "thought": thought,
            "handoff": handoff.model_dump() if handoff else {"raw_response": raw_text},
        }

        history = list(state.get("agent_history", []))
        history.append(log_entry)

        return {
            "coder_proposals": proposals_dict,
            "agent_history": history,
            "messages": [
                Message(role="assistant", content=f"Coder proposed changes:\n{raw_text}")
            ],
        }
