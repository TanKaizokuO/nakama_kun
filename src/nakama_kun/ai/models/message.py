from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    """Represents a tool call requested by the LLM."""

    id: str
    type: Literal["function"] = "function"
    function: dict[str, Any]  # Must contain 'name' and 'arguments'


class Message(BaseModel):
    """Represents a chat message within the conversation history."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    name: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
