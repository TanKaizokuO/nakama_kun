from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from nakama_kun.ai.models.message import Message
from nakama_kun.ai.models.plan import Plan
from nakama_kun.orchestration.evidence import EvidenceStore
from nakama_kun.orchestration.verification import VerificationReport


class AgentState(TypedDict):
    """The central state maintained throughout the LangGraph agent workflow."""

    # The user's input request/goal
    goal: str

    # The structured plan built by the Planner node
    plan: Plan | None

    # The running log of LLM chat messages (accumulates over node execution)
    messages: Annotated[list[Message], operator.add]

    # Log of tools that were run during the task
    tool_results: Annotated[list[dict[str, Any]], operator.add]

    # Structured workspace verification snapshot produced by the Verifier node.
    # Contains real file contents, command exit codes, and workspace listings —
    # the Reviewer evaluates this instead of raw tool summaries.
    verification_report: VerificationReport | None

    # Structured evidence store containing preserved tool outputs, validations, etc.
    evidence_store: EvidenceStore | None

    # Feedback from the Reviewer node if work needs adjustment
    reviewer_feedback: str | None

    # Retry count to prevent infinite planning/execution loops
    retry_count: int

    # Final synthesized answer for the user
    final_response: str | None

    # Current execution phase status: planning, executing, reviewing, done, failed
    status: str
