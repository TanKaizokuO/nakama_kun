from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger

from nakama_kun.agents.base import BaseAgent
from nakama_kun.agents.models import ReviewerHandoff
from nakama_kun.agents.prompts import REVIEWER_AGENT_PROMPT
from nakama_kun.ai.models.message import Message


def parse_reviewer_handoff(text: str) -> ReviewerHandoff | None:
    """Parse a structured ReviewerHandoff model from JSON text or code blocks."""
    text_stripped = text.strip()
    try:
        data = json.loads(text_stripped)
        return ReviewerHandoff.model_validate(data)
    except Exception:
        pass

    # Try matching json block ```json ... ```
    match = re.search(r"```json\s*(.*?)\s*```", text_stripped, re.DOTALL | re.IGNORECASE)
    if match:
        try:
            data = json.loads(match.group(1).strip())
            return ReviewerHandoff.model_validate(data)
        except Exception:
            pass

    # Try matching general block ``` ... ```
    match = re.search(r"```\s*(.*?)\s*```", text_stripped, re.DOTALL | re.IGNORECASE)
    if match:
        try:
            data = json.loads(match.group(1).strip())
            return ReviewerHandoff.model_validate(data)
        except Exception:
            pass

    return None


class ReviewerAgent(BaseAgent):
    """Reviewer Agent evaluates verification reports to approve or reject tasks."""

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        logger.info("[ReviewerAgent] Starting review task...")
        goal = state["goal"]
        plan = state.get("plan")
        report = state.get("verification_report")

        # 1. Format verification report text
        report_text = ""
        if report:
            report_text = report.to_reviewer_text()
        else:
            report_text = "No verification report available."

        # 2. Build user prompt
        user_prompt_lines = [
            f"Goal: {goal}",
            f"Plan Summary: {plan.goal_summary if plan else 'none'}",
            f"\n### Verification Report\n{report_text}"
        ]
        user_prompt = "\n".join(user_prompt_lines)

        # 3. Call LLM
        messages = [
            Message(role="system", content=REVIEWER_AGENT_PROMPT),
            Message(role="user", content=user_prompt)
        ]
        response = await self.chat_service.provider.generate(messages)
        raw_text = response.content or ""

        # 4. Parse Handoff
        handoff = parse_reviewer_handoff(raw_text)

        # 5. Extract results with fallbacks if parsing fails
        if handoff:
            approved = handoff.approved
            feedback = handoff.feedback
            route_to = handoff.route_to
            bugs = handoff.bugs
            risks = handoff.risks
        else:
            logger.warning("[ReviewerAgent] Failed to parse structured ReviewerHandoff. Falling back to pre-computed signal.")
            if report:
                signal = report.evaluate_outcome()
                approved = (signal.recommendation == "APPROVE")
                feedback = signal.reason
                route_to = "coder" if signal.any_test_failed else "planner"
                bugs = ["Verification check failed."] if not approved else []
                risks = []
            else:
                approved = False
                feedback = "Missing verification report."
                route_to = "planner"
                bugs = []
                risks = []

        # Enforce valid routing
        if not approved and route_to not in ("planner", "coder"):
            route_to = "coder" if (report and report.evaluate_outcome().any_test_failed) else "planner"

        # 6. Log decisions to agent_history
        thought = f"Review completed. Approved: {approved}. Route to: {route_to}."
        log_entry = {
            "agent": "ReviewerAgent",
            "thought": thought,
            "handoff": {
                "approved": approved,
                "route_to": route_to,
                "bugs": bugs,
                "risks": risks,
                "feedback": feedback
            }
        }
        history = list(state.get("agent_history", []))
        history.append(log_entry)

        # Build updates matching make_reviewer_node
        status = "done" if approved else "planning"

        return {
            "reviewer_feedback": feedback if not approved else None,
            "reviewer_route": route_to if not approved else None,
            "status": status,
            "agent_history": history,
            "messages": [
                Message(role="assistant", content=f"Reviewer results:\n{raw_text}")
            ]
        }
