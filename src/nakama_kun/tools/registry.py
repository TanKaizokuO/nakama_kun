"""
tools/registry.py — Central registry for nakama_kun tools.

Tools are registered once at application start-up. The registry can then:
- Look up a tool by name for dispatch.
- Export all tool JSON schemas for the provider ``tools=`` parameter.
"""

from __future__ import annotations

from typing import Any

from nakama_kun.mcp.registry import MCPRegistry
from nakama_kun.tools.adapters import MCPToolAdapter
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
        if name in self._tools:
            return self._tools[name]

        # Look in MCP registry
        mcp_tool = MCPRegistry.get_instance().find_tool(name)
        if mcp_tool is not None:
            return MCPToolAdapter(mcp_tool)

        raise UnknownToolError(
            f"No tool named '{name}' is registered. "
            f"Available: {self.names()}"
        )

    def all_schemas(self) -> list[dict[str, Any]]:
        """Return a list of OpenAI-compatible tool schemas for all registered tools."""
        schemas = [tool.to_schema() for tool in self._tools.values()]
        for mcp_tool in MCPRegistry.get_instance().list_tools():
            adapter = MCPToolAdapter(mcp_tool)
            schemas.append(adapter.to_schema())
        return schemas

    def names(self) -> list[str]:
        """Return the sorted names of all registered tools."""
        mcp_names = [t.name for t in MCPRegistry.get_instance().list_tools()]
        return sorted(list(self._tools.keys()) + mcp_names)

    def __len__(self) -> int:
        return len(self._tools) + len(MCPRegistry.get_instance().list_tools())
