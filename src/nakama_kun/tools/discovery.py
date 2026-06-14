from __future__ import annotations

from typing import Any

from nakama_kun.tools.interfaces import UnifiedTool
from nakama_kun.tools.registry import ToolRegistry


class ToolDiscoveryService:
    """Service to discover and retrieve schema information for local and MCP tools."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def list_available_tools(self) -> list[UnifiedTool]:
        """Returns all available local and adapted MCP tools."""
        tools: list[UnifiedTool] = []
        for name in self.registry.names():
            try:
                tool = self.registry.get(name)
                tools.append(tool)
            except Exception:
                pass
        return tools

    def find_tool(self, name: str) -> UnifiedTool | None:
        """Finds a local or MCP tool by name."""
        try:
            return self.registry.get(name)
        except Exception:
            return None

    def get_tool_schema(self, name: str) -> dict[str, Any] | None:
        """Retrieves the parameter schema for a tool."""
        tool = self.find_tool(name)
        if tool is not None:
            return tool.schema
        return None
