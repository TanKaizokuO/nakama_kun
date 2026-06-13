from __future__ import annotations

from datetime import datetime, UTC
from pydantic import BaseModel, Field


class SuccessfulTask(BaseModel):
    """Represents a successfully completed task experience."""

    goal: str = Field(description="The original user goal.")
    plan_summary: str = Field(description="Summary of the execution plan.")
    files_changed: list[str] = Field(default_factory=list, description="Files created or modified.")
    tools_used: list[str] = Field(default_factory=list, description="List of tools invoked.")
    outcome: str = Field(description="Outcome explanation or final response snippet.")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Time of completion.")
    success_frequency: int = Field(default=0, description="The cumulative number of times this success was referenced.")


class FailureRecord(BaseModel):
    """Represents a task failure or intermediate QA rejection."""

    goal: str = Field(description="The user goal when failure occurred.")
    attempted_actions: list[str] = Field(default_factory=list, description="Actions executed before failure.")
    failure_type: str = Field(description="Category of failure (e.g. QA_REJECTION, TEST_FAILURE, MISSING_ARTIFACTS).")
    failure_message: str = Field(description="Rejection feedback or compile/test error message.")
    resolution: str = Field(description="Determined route or planned correction.")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Time of failure.")
    failure_frequency: int = Field(default=0, description="The cumulative number of times this failure occurred/was referenced.")



class UserPreference(BaseModel):
    """Represents a learned user preference or environment choices (linter, frameworks, validations)."""

    key: str = Field(description="Preference key.")
    value: str = Field(description="Preference value.")
    confidence: float = Field(description="Calculated confidence level [0.0, 1.0].")
    source: str = Field(description="Source of the preference extraction (user_goal or project_dependencies).")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Time of last update.")
