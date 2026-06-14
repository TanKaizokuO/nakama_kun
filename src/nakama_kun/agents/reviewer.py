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


CODE_REVIEW_PROMPT = """You are a specialized Reviewer Agent performing a CODE_REVIEW.
Your role is to evaluate workspace verification reports (existence checks, command results, test outputs) to find bugs, compile failures, or missing files.
Determine whether the task was fully accomplished and verify code correctness.

You MUST evaluate the following:
1. Files modified: Are all planned/necessary files created or modified correctly?
2. Tests passed: Have all test suites run and passed successfully?
3. Implementation quality: Is the code clean, robust, and matches requirements?

Respond with a JSON object. Do not include any text outside the JSON block.
Use this JSON schema:
{
  "approved": true or false,
  "feedback": "Detailed feedback or reasons for rejection if approved is false, else null.",
  "route_to": "coder" or "planner" or null,
  "bugs": ["list of identified bugs or test failures"],
  "risks": ["list of architectural or security risks"]
}

Guidelines for routing rejections:
- Choose 'coder' if the code contains bugs, typos, missing imports, or if unit tests failed.
- Choose 'planner' if the overall approach was incorrect, if the planned files were structurally missing, or if major goals were misunderstood.
"""

RETRIEVAL_REVIEW_PROMPT = """You are a specialized Reviewer Agent performing a RETRIEVAL_REVIEW.
Your role is to evaluate whether the retrieval task has been fully accomplished by inspecting the tool outputs and evidence.
The primary deliverable is INFORMATION (e.g. directory listing, file content, version output), not a file artifact.

You MUST evaluate the following:
1. Information retrieved: Is the requested information successfully retrieved?
2. Evidence present: Is the retrieved information present in the tool outputs/evidence?
3. Answer completeness: Is the retrieved information complete and answers the goal?
4. No unnecessary mutations: Ensure no files were mutated/created and no packages installed.

CRITICAL RULES:
- You must NOT reject the task because "no files changed" or "no files were created on disk". Retrieval tasks do not write files.
- You must NOT reject the task because "no tests ran". Retrieval tasks do not have/need unit tests.

Respond with a JSON object. Do not include any text outside the JSON block.
Use this JSON schema:
{
  "approved": true or false,
  "feedback": "Detailed feedback or reasons for rejection if approved is false, else null.",
  "route_to": "planner" or null,
  "bugs": ["list of identified information retrieval issues"],
  "risks": ["list of security violations or issues"]
}

Guidelines for routing rejections:
- Since this is a retrieval task, if the information was not retrieved or is incomplete, route back to 'planner' to retry or gather details.
"""


class ReviewerAgent(BaseAgent):
    """Reviewer Agent evaluates verification reports to approve or reject tasks."""

    def __init__(self, chat_service: Any) -> None:
        from nakama_kun.agents.prompts import REVIEWER_AGENT_PROMPT
        super().__init__(
            name="ReviewerAgent",
            role="reviewer",
            system_prompt=REVIEWER_AGENT_PROMPT,
            chat_service=chat_service,
        )
        self.memory["review_history"] = []

    @property
    def review_history(self) -> list[Any]:
        """Returns the history of reviews performed by the reviewer."""
        return self.memory.get("review_history", [])

    async def review(self, state: dict[str, Any]) -> dict[str, Any]:
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

        task_type = state.get("task_type") or "MODIFICATION"
        goal_satisfied = state.get("goal_satisfied", False)

        # 2. Select review mode and build user prompt
        if task_type == "RETRIEVAL":
            review_mode = "RETRIEVAL_REVIEW"
            system_prompt = RETRIEVAL_REVIEW_PROMPT
            user_prompt_lines = [
                f"Goal: {goal}",
                f"Plan Summary: {plan.goal_summary if plan else 'none'}",
                f"Review Mode: {review_mode}",
                f"Goal Satisfied (Evidence Collected): {goal_satisfied}",
                "\n### Verification/Evidence Report",
                report_text,
            ]
        else:
            review_mode = "CODE_REVIEW"
            system_prompt = CODE_REVIEW_PROMPT
            user_prompt_lines = [
                f"Goal: {goal}",
                f"Plan Summary: {plan.goal_summary if plan else 'none'}",
                f"Review Mode: {review_mode}",
                "\n### Verification/Evidence Report",
                report_text,
            ]
            
        user_prompt = "\n".join(user_prompt_lines)

        # 3. Call LLM
        messages = [
            Message(role="system", content=system_prompt),
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
                approved = (signal.recommendation == "APPROVE") or (task_type == "RETRIEVAL" and goal_satisfied)
                feedback = signal.reason
                route_to = "coder" if (task_type != "RETRIEVAL" and signal.any_test_failed) else "planner"
                bugs = ["Verification check failed."] if not approved else []
                risks = []
            else:
                approved = (task_type == "RETRIEVAL" and goal_satisfied)
                feedback = None if approved else "Missing verification report."
                route_to = None if approved else "planner"
                bugs = []
                risks = []

        # Enforce valid routing
        if not approved and route_to not in ("planner", "coder"):
            route_to = "coder" if (task_type != "RETRIEVAL" and report and report.evaluate_outcome().any_test_failed) else "planner"

        # 6. Log decisions to agent_history
        thought = f"Review completed ({review_mode}). Approved: {approved}. Route to: {route_to}."
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
