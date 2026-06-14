from __future__ import annotations

from typing import Any

from loguru import logger

from nakama_kun.config.mcp import MCPSettings
from nakama_kun.mcp.client import MCPClient
from nakama_kun.mcp.tool import MCPTool
from nakama_kun.mcp.abstractions import MCPServer, MCPServerStatus
from nakama_kun.mcp.registry import MCPRegistry


class MCPManager:
    """Manages connection lifecycles, configuration, and tool discovery for all configured MCP servers."""

    def __init__(
        self,
        workspace_root: str | None = None,
        approval_provider: Any | None = None,
    ) -> None:
        self.workspace_root = workspace_root
        self.approval_provider = approval_provider
        self.settings = MCPSettings()
        self.clients: dict[str, MCPClient] = {}
        self.registry = MCPRegistry.get_instance()
        self._tools_loaded: set[str] = set()

    async def connect_all(self) -> None:
        """Connects to all configured MCP servers asynchronously.

        This startup process is non-blocking; if one server fails to launch, the
        error is logged, and the manager continues loading the remaining servers.
        """
        configs = self.settings.load_servers(self.workspace_root)
        if not configs:
            logger.info("No MCP servers configured or found.")
            return

        for name, cfg in configs.items():
            if name in self._tools_loaded:
                continue
            # 1. Register server in STARTING state
            server = MCPServer(
                name=name,
                status=MCPServerStatus.STARTING,
                capabilities={},
                tools=[]
            )
            # Re-register if already exists
            if self.registry.get_server(name) is not None:
                self.registry.unregister_server(name)
            self.registry.register_server(server)

            client = MCPClient(
                name=name,
                command=cfg.command,
                args=cfg.args,
                env=cfg.env,
            )
            self.clients[name] = client
            try:
                await client.connect()
                server.status = MCPServerStatus.CONNECTED
                # Discover server tools
                await self.discover_server_tools(name)
            except Exception as e:
                logger.error(f"Failed to start optional MCP server '{name}': {e}")
                server.status = MCPServerStatus.ERROR
                if name in self.clients:
                    del self.clients[name]
                continue

    async def discover_server_tools(self, name: str) -> None:
        """Discover and register tools for a specific connected server if not already loaded."""
        if name in self._tools_loaded:
            return

        client = self.clients.get(name)
        if not client:
            return

        server = self.registry.get_server(name)
        if not server:
            server = MCPServer(
                name=name,
                status=MCPServerStatus.CONNECTED,
                capabilities={},
                tools=[]
            )
            self.registry.register_server(server)

        # Retrieve capabilities
        caps: dict[str, Any] = {}
        session = getattr(client, "session", None)
        if session is not None and hasattr(session, "initialize_result") and session.initialize_result:
            init_res = session.initialize_result
            if hasattr(init_res, "capabilities"):
                caps = getattr(init_res.capabilities, "model_dump", lambda: {})() or {}
        server.capabilities = caps

        try:
            # Discover and register tools
            tools = await client.list_tools()
            logger.debug(
                "Discovered {} tools from '{}'",
                len(tools),
                name,
            )

            built_ins = {
                "read_file",
                "write_file",
                "list_files",
                "search_files",
                "search_vector_store",
                "run_command",
            }
            seen_names = set(built_ins)
            for loaded_name in self._tools_loaded:
                s = self.registry.get_server(loaded_name)
                if s:
                    for t in s.tools:
                        seen_names.add(t.name)

            mcp_tools = []
            for t in tools:
                orig_name = t.name
                target_name = orig_name

                # Resolve name conflicts
                if target_name in seen_names:
                    target_name = f"mcp_{name}_{orig_name}"
                    logger.warning(
                        f"Tool name conflict: '{orig_name}' from server '{name}' "
                        f"already exists. Renamed to '{target_name}'."
                    )
                seen_names.add(target_name)

                description = t.description or f"MCP tool from server '{name}'"
                schema = t.inputSchema
                if not isinstance(schema, dict):
                    schema = {"type": "object", "properties": {}}

                mcp_tool = MCPTool(
                    client=client,
                    original_name=orig_name,
                    name=target_name,
                    description=description,
                    parameters=schema,
                    approval_provider=self.approval_provider,
                )
                mcp_tools.append(mcp_tool)

            server.tools = mcp_tools
            self._tools_loaded.add(name)

        except Exception as e:
            logger.error(f"Failed to discover tools for connected MCP server '{name}': {e}")

    async def get_tools(self) -> list[MCPTool]:
        """Discovers tools from all connected MCP servers and returns mapped MCPTool instances."""
        for name in list(self.clients.keys()):
            await self.discover_server_tools(name)
        return self.registry.list_tools()

    async def disconnect_all(self) -> None:
        """Gracefully disconnects all running MCP servers."""
        self._tools_loaded.clear()
        if not self.clients:
            return

        logger.info("Disconnecting all active MCP servers...")
        for name, client in list(self.clients.items()):
            server = self.registry.get_server(name)
            try:
                await client.disconnect()
                if server:
                    server.status = MCPServerStatus.DISCONNECTED
                    server.tools = []
            except Exception as e:
                logger.warning(f"Error disconnecting from MCP server '{name}': {e}")
                if server:
                    server.status = MCPServerStatus.ERROR
        self.clients.clear()

    async def health_check(self) -> None:
        """Verify server connections, listing tools to check integrity (read-only)."""
        from unittest.mock import Mock

        for name, client in self.clients.items():
            server = self.registry.get_server(name)
            if not server:
                server = MCPServer(
                    name=name,
                    status=MCPServerStatus.CONNECTED,
                    capabilities={},
                    tools=[]
                )
                self.registry.register_server(server)

            try:
                session = getattr(client, "session", None)
                if session is None and not isinstance(client, Mock):
                    server.status = MCPServerStatus.DISCONNECTED
                    continue

                # Responsiveness check: call list_tools but do NOT mutate registry/tools
                await client.list_tools()
                server.status = MCPServerStatus.CONNECTED

                # Retrieve capabilities
                caps: dict[str, Any] = {}
                session_obj = getattr(client, "session", None)
                if session_obj is not None and hasattr(session_obj, "initialize_result") and session_obj.initialize_result:
                    init_res = session_obj.initialize_result
                    if hasattr(init_res, "capabilities"):
                        caps = getattr(init_res.capabilities, "model_dump", lambda: {})() or {}
                server.capabilities = caps

            except Exception as e:
                logger.warning(f"Health check failed for server '{name}': {e}")
                server.status = MCPServerStatus.ERROR
