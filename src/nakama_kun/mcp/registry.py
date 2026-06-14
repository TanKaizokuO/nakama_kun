from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nakama_kun.mcp.abstractions import MCPServer
    from nakama_kun.mcp.tool import MCPTool


class MCPRegistry:
    """Singleton registry holding Model Context Protocol servers and synchronized tools."""

    _instance: MCPRegistry | None = None

    @classmethod
    def get_instance(cls) -> MCPRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self.servers: dict[str, MCPServer] = {}

    def register_server(self, server: MCPServer) -> None:
        """Register a new server. Raises ValueError if name is already registered."""
        if server.name in self.servers:
            raise ValueError(f"Duplicate registration: Server '{server.name}' already registered.")
        self.servers[server.name] = server

    def unregister_server(self, name: str) -> None:
        """Unregister a server by name."""
        if name in self.servers:
            del self.servers[name]

    def get_server(self, name: str) -> MCPServer | None:
        """Retrieve a registered server by name."""
        return self.servers.get(name)

    def list_servers(self) -> list[MCPServer]:
        """List all registered servers."""
        return list(self.servers.values())

    def list_tools(self) -> list[MCPTool]:
        """Collect and return all tools across all registered servers."""
        all_tools: list[MCPTool] = []
        for server in self.servers.values():
            all_tools.extend(server.tools)
        return all_tools

    def find_tool(self, name: str) -> MCPTool | None:
        """Find a specific tool by its resolved name across all servers."""
        for server in self.servers.values():
            for tool in server.tools:
                if tool.name == name:
                    return tool
        return None
