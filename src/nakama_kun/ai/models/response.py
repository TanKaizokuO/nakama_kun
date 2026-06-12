from pydantic import BaseModel, Field

from nakama_kun.ai.models.message import ToolCall


class TokenUsage(BaseModel):
    """Token usage tracking statistics."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class AIResponse(BaseModel):
    """The structured output format returned by the AI provider layer."""

    content: str | None = None
    model: str
    usage: TokenUsage = Field(default_factory=TokenUsage)
    finish_reason: str | None = None
    latency: float = 0.0
    tool_calls: list[ToolCall] | None = None
