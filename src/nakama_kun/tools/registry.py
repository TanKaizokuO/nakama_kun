"""
tools/registry.py — Central registry for nakama_kun tools.

Tools are registered once at application start-up. The registry can then:
- Look up a tool by name for dispatch.
- Export all tool JSON schemas for the provider ``tools=`` parameter.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

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
        tool_name = tool.name
        if hasattr(tool, "server_name"):
            server_name = tool.server_name
        elif hasattr(tool, "mcp_tool") and hasattr(tool.mcp_tool, "server_name"):
            server_name = tool.mcp_tool.server_name
        else:
            server_name = "local"

        # Explicitly protect core built-in tools from shadowing/replacing
        PROTECTED_BUILTIN_TOOLS = {
            "read_file",
            "write_file",
            "list_files",
            "search_files",
            "search_vector_store",
            "run_command",
        }

        if tool_name in PROTECTED_BUILTIN_TOOLS and tool_name in self._tools:
            logger.info(
                "Duplicate prevention: protected built-in tool '{}' cannot be shadowed or overwritten by server '{}', skipping.",
                tool_name,
                server_name,
            )
            return

        logger.debug(
            "Registering tool '{}' from server '{}'",
            tool_name,
            server_name,
        )

        before = len(self)
        if tool_name not in self._tools:
            self._tools[tool_name] = tool
        else:
            logger.info(
                "Duplicate prevention: tool '{}' already registered in ToolRegistry, skipping.",
                tool_name,
            )
        after = len(self)

        logger.debug(
            "Registry size before={} after={}",
            before,
            after,
        )

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
        schemas = {tool.name: tool.to_schema() for tool in self._tools.values()}
        for mcp_tool in MCPRegistry.get_instance().list_tools():
            if mcp_tool.name not in schemas:
                adapter = MCPToolAdapter(mcp_tool)
                schemas[mcp_tool.name] = adapter.to_schema()
        return list(schemas.values())

    def names(self) -> list[str]:
        """Return the sorted names of all registered tools."""
        mcp_names = [t.name for t in MCPRegistry.get_instance().list_tools()]
        return sorted(list(set(self._tools.keys()) | set(mcp_names)))

    def __len__(self) -> int:
        mcp_names = [t.name for t in MCPRegistry.get_instance().list_tools()]
        return len(set(self._tools.keys()) | set(mcp_names))
