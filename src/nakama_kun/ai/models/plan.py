import json
import re

from pydantic import BaseModel, Field


class Plan(BaseModel):
    """Structured implementation plan model."""

    goal_summary: str = Field(description="A concise summary of the goal to be achieved.")
    assumptions: list[str] = Field(default_factory=list, description="Assumptions made during planning.")
    ordered_steps: list[str] = Field(default_factory=list, description="Discrete, ordered steps to execute the plan.")
    risks: list[str] = Field(default_factory=list, description="Potential risks or pitfalls.")
    validation_checklist: list[str] = Field(default_factory=list, description="A checklist of items to verify completion.")
    targets: list[str] = Field(default_factory=list, description="Optional target files or modules involved.")


def parse_plan(text: str) -> Plan | None:
    """Attempt to parse a structured Plan from the given text.

    Supports direct JSON parse, parsing from a ```json markdown block,
    or parsing from a general ``` markdown block.
    """
    text_stripped = text.strip()
    try:
        data = json.loads(text_stripped)
        return Plan.model_validate(data)
    except Exception:
        pass

    # Try matching json block ```json ... ```
    match = re.search(r"```json\s*(.*?)\s*```", text_stripped, re.DOTALL | re.IGNORECASE)
    if match:
        try:
            data = json.loads(match.group(1).strip())
            return Plan.model_validate(data)
        except Exception:
            pass

    # Try matching general block ``` ... ```
    match = re.search(r"```\s*(.*?)\s*```", text_stripped, re.DOTALL | re.IGNORECASE)
    if match:
        try:
            data = json.loads(match.group(1).strip())
            return Plan.model_validate(data)
        except Exception:
            pass

    return None
