from __future__ import annotations

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
