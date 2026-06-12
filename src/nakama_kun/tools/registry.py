"""
tools/registry.py — Central registry for nakama_kun tools.

Tools are registered once at application start-up. The registry can then:
- Look up a tool by name for dispatch.
- Export all tool JSON schemas for the provider ``tools=`` parameter.
"""

from __future__ import annotations

from typing import Any

from nakama_kun.tools.exceptions import UnknownToolError
from nakama_kun.tools.interfaces import BaseTool


class ToolRegistry:
    """Holds all registered :class:`~nakama_kun.tools.interfaces.BaseTool` instances."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Add *tool* to the registry.  Silently overwrites any prior entry."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        """Return the tool registered under *name*.

        Raises:
            UnknownToolError: If no tool with *name* is registered.
        """
        try:
            return self._tools[name]
        except KeyError:
            raise UnknownToolError(
                f"No tool named '{name}' is registered. "
                f"Available: {sorted(self._tools)}"
            ) from None

    def all_schemas(self) -> list[dict[str, Any]]:
        """Return a list of OpenAI-compatible tool schemas for all registered tools."""
        return [tool.to_schema() for tool in self._tools.values()]

    def names(self) -> list[str]:
        """Return the sorted names of all registered tools."""
        return sorted(self._tools)

    def __len__(self) -> int:
        return len(self._tools)
