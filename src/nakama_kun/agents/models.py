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

