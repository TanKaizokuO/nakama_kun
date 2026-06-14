"""
tools/interfaces.py — Abstract base class and result types for the tool layer.

All concrete tools subclass ``BaseTool`` and return a ``ToolResult``.
The ``to_schema()`` helper produces an OpenAI-compatible function-tool dict
that can be passed directly to the provider's ``tools=`` parameter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Structured outcome returned by every tool execution."""

    success: bool
    output: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_content(self) -> str:
        """Render the result as a plain-text tool-result message content."""
        if self.success:
            return self.output or ""
        error = self.error or self.output or "unknown error"
        content = f"ERROR: {error}"
        if self.output and self.output != error:
            content += f"\n\nOutput:\n{self.output}"
        return content


class UnifiedTool(ABC):
    """Abstract base representing any tool (local or MCP) that can be queried and executed."""

    name: str
    description: str

    @property
    @abstractmethod
    def schema(self) -> dict[str, Any]:
        """OpenAI-compatible function schema representation."""
        ...

    @property
    @abstractmethod
    def permissions(self) -> list[str]:
        """Permissions required by this tool."""
        ...

    @property
    @abstractmethod
    def categories(self) -> list[str]:
        """Categories this tool belongs to."""
        ...

    @property
    @abstractmethod
    def usage_description(self) -> str:
        """Detailed usage description."""
        ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Run the tool with keyword arguments and return a standardized ToolResult."""
        ...


class BaseTool(UnifiedTool, ABC):
    """Abstract base class every nakama_kun tool must implement.

    Subclasses declare:
        name        — unique identifier used by the LLM to call the tool.
        description — human/LLM-readable description of what the tool does.
        parameters  — JSON-schema ``object`` describing accepted arguments.

    The ``execute`` method receives keyword arguments matching the schema and
    must return a ``ToolResult``.  It should never raise — catch internally
    and return a ``ToolResult(success=False, error=...)`` instead.
    """

    parameters: dict[str, Any]

    @property
    def permissions(self) -> list[str]:
        """Permissions required by this tool."""
        return []

    @property
    def categories(self) -> list[str]:
        """Categories this tool belongs to."""
        return []

    @property
    def usage_description(self) -> str:
        """Detailed usage description."""
        return self.description

    @property
    def schema(self) -> dict[str, Any]:
        """Return the tool parameters schema."""
        return self.parameters

    def to_schema(self) -> dict[str, Any]:
        """Return an OpenAI function-tool dict for the provider ``tools=`` list."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
