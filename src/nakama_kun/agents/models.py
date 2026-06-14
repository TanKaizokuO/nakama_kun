from __future__ import annotations

import time
from typing import Any
from pydantic import BaseModel, Field


class CodeProposal(BaseModel):
    """A single file change proposed by the Coder Agent."""

    path: str = Field(description="Relative path to the workspace file to be created or modified.")
    content: str = Field(description="Complete text content for the file.")
    explanation: str = Field(description="Explanation of why this change is necessary.")


class CoderHandoff(BaseModel):
    """The structured state passed from the Coder Agent to the Executor Agent."""

    proposals: list[CodeProposal] = Field(default_factory=list, description="List of proposed file modifications.")
    notes: str = Field(default="", description="General execution notes for the Executor Agent.")


class ReviewerHandoff(BaseModel):
    """The structured feedback returned by the Reviewer Agent."""

    approved: bool = Field(description="Set to true if implementation is correct, complete, and passes tests.")
    feedback: str | None = Field(default=None, description="Detailed explanation/reasons for rejection if approved=False.")
    route_to: str | None = Field(
        default=None,
        description="Target destination for rejection loops. Must be either 'planner' or 'coder'.",
    )
    bugs: list[str] = Field(default_factory=list, description="List of identified bugs, code style issues, or test failures.")
    risks: list[str] = Field(default_factory=list, description="Identified architectural risks or security concerns.")


class RetrievalPackage(BaseModel):
    """The structured state representing repository search results, summaries, and citations."""

    retrieved_files: list[str] = Field(default_factory=list, description="List of relevant retrieved files.")
    summaries: dict[str, str] = Field(default_factory=dict, description="Brief summary of what each file implements/contains.")
    citations: dict[str, str] = Field(default_factory=dict, description="Citations/source context mapping for each file.")
    relevance_scores: dict[str, float] = Field(default_factory=dict, description="Semantic relevance score for each file.")


def parse_retrieval_package(text: str) -> RetrievalPackage | None:
    """Parse a structured RetrievalPackage model from JSON text or code blocks."""
    import json
    import re
    text_stripped = text.strip()
    try:
        data = json.loads(text_stripped)
        return RetrievalPackage.model_validate(data)
    except Exception:
        pass

    # Try matching json block ```json ... ```
    match = re.search(r"```json\s*(.*?)\s*```", text_stripped, re.DOTALL | re.IGNORECASE)
    if match:
        try:
            data = json.loads(match.group(1).strip())
            return RetrievalPackage.model_validate(data)
        except Exception:
            pass

    # Try matching general block ``` ... ```
    match = re.search(r"```\s*(.*?)\s*```", text_stripped, re.DOTALL | re.IGNORECASE)
    if match:
        try:
            data = json.loads(match.group(1).strip())
            return RetrievalPackage.model_validate(data)
        except Exception:
            pass

    return None


class TestExecutionReport(BaseModel):
    """The structured state representing test execution results and recommendations."""

    passed: int = Field(description="Number of passed tests.")
    failed: int = Field(description="Number of failed tests.")
    skipped: int = Field(description="Number of skipped tests.")
    errors: int = Field(description="Number of error tests.")
    recommendations: list[str] = Field(default_factory=list, description="Recommendations for implementation/test repairs.")


def parse_test_report(text: str) -> TestExecutionReport | None:
    """Parse a structured TestExecutionReport model from JSON text or code blocks."""
    import json
    import re
    text_stripped = text.strip()
    try:
        data = json.loads(text_stripped)
        return TestExecutionReport.model_validate(data)
    except Exception:
        pass

    # Try matching json block ```json ... ```
    match = re.search(r"```json\s*(.*?)\s*```", text_stripped, re.DOTALL | re.IGNORECASE)
    if match:
        try:
            data = json.loads(match.group(1).strip())
            return TestExecutionReport.model_validate(data)
        except Exception:
            pass

    # Try matching general block ``` ... ```
    match = re.search(r"```\s*(.*?)\s*```", text_stripped, re.DOTALL | re.IGNORECASE)
    if match:
        try:
            data = json.loads(match.group(1).strip())
            return TestExecutionReport.model_validate(data)
        except Exception:
            pass

    return None


class SecurityReport(BaseModel):
    """The structured state representing a code/command security review."""

    warnings: list[str] = Field(default_factory=list, description="List of general security warnings/risks.")
    vulnerabilities: list[str] = Field(default_factory=list, description="Identified security vulnerabilities (e.g. hardcoded secrets).")
    blocked_actions: list[str] = Field(default_factory=list, description="Unsafe actions or commands that should be blocked.")
    remediation_suggestions: list[str] = Field(default_factory=list, description="Suggestions for fixing identified security issues.")


def parse_security_report(text: str) -> SecurityReport | None:
    """Parse a structured SecurityReport model from JSON text or code blocks."""
    import json
    import re
    text_stripped = text.strip()
    try:
        data = json.loads(text_stripped)
        return SecurityReport.model_validate(data)
    except Exception:
        pass

    # Try matching json block ```json ... ```
    match = re.search(r"```json\s*(.*?)\s*```", text_stripped, re.DOTALL | re.IGNORECASE)
    if match:
        try:
            data = json.loads(match.group(1).strip())
            return SecurityReport.model_validate(data)
        except Exception:
            pass

    # Try matching general block ``` ... ```
    match = re.search(r"```\s*(.*?)\s*```", text_stripped, re.DOTALL | re.IGNORECASE)
    if match:
        try:
            data = json.loads(match.group(1).strip())
            return SecurityReport.model_validate(data)
        except Exception:
            pass

    return None


class AgentMessage(BaseModel):
    """A structured message sent between agents."""

    sender: str = Field(description="The name or role of the sending agent.")
    receiver: str = Field(description="The name or role of the receiving agent.")
    message_type: str = Field(description="The type/intent of message, e.g. request_information, share_findings, submit_recommendations.")
    payload: dict[str, Any] = Field(default_factory=dict, description="The message data payload.")
    timestamp: float = Field(default_factory=time.time, description="Unix timestamp of when the message was sent.")


class TaskDelegation(BaseModel):
    """A task delegation assigned by the Supervisor Agent."""

    task: str = Field(description="Detailed description of the task to be performed.")
    assigned_agent: str = Field(description="The name or role of the agent assigned to this task.")
    priority: int = Field(default=1, description="Priority level of the task.")
    dependencies: list[str] = Field(default_factory=list, description="List of task descriptions or agent roles this task depends on.")
    status: str = Field(default="pending", description="Current status of the delegation: pending, running, completed, failed.")


class SupervisorDecision(BaseModel):
    """Structured decision returned by the Supervisor Agent."""

    rationale: str = Field(description="Detailed explanation/reasoning of the supervisor's choices.")
    next_agents: list[str] = Field(description="List of agent roles/names to execute next (multiple values mean parallel execution).")
    delegations: list[TaskDelegation] = Field(default_factory=list, description="The list of task delegations managed by the supervisor.")
    status: str = Field(description="The overall task status: planning, executing, reviewing, done, failed.")


def parse_supervisor_decision(text: str) -> SupervisorDecision | None:
    """Parse a structured SupervisorDecision model from JSON text or code blocks."""
    import json
    import re
    text_stripped = text.strip()
    try:
        data = json.loads(text_stripped)
        return SupervisorDecision.model_validate(data)
    except Exception:
        pass

    # Try matching json block ```json ... ```
    match = re.search(r"```json\s*(.*?)\s*```", text_stripped, re.DOTALL | re.IGNORECASE)
    if match:
        try:
            data = json.loads(match.group(1).strip())
            return SupervisorDecision.model_validate(data)
        except Exception:
            pass

    # Try matching general block ``` ... ```
    match = re.search(r"```\s*(.*?)\s*```", text_stripped, re.DOTALL | re.IGNORECASE)
    if match:
        try:
            data = json.loads(match.group(1).strip())
            return SupervisorDecision.model_validate(data)
        except Exception:
            pass

    return None



