from __future__ import annotations

from typing import Any

from loguru import logger

from nakama_kun.config.mcp import MCPSettings
from nakama_kun.mcp.client import MCPClient
from nakama_kun.mcp.tool import MCPTool


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
            client = MCPClient(
                name=name,
                command=cfg.command,
                args=cfg.args,
                env=cfg.env,
            )
            try:
                await client.connect()
                self.clients[name] = client
            except Exception as e:
                logger.error(f"Failed to start optional MCP server '{name}': {e}")

    async def get_tools(self) -> list[MCPTool]:
        """Discovers tools from all connected MCP servers and returns mapped MCPTool instances.

        Automatically resolves tool name conflicts with built-in tools or other
        MCP servers by prefixing the tool name (e.g., 'mcp_server_name_tool_name').
        """
        built_ins = {
            "read_file",
            "write_file",
            "list_files",
            "search_files",
            "search_vector_store",
            "run_command",
        }
        seen_names = set(built_ins)
        mcp_tools: list[MCPTool] = []

        for client in self.clients.values():
            try:
                tools = await client.list_tools()
                for t in tools:
                    orig_name = t.name
                    target_name = orig_name

                    # Resolve name conflicts
                    if target_name in seen_names:
                        target_name = f"mcp_{client.name}_{orig_name}"
                        logger.warning(
                            f"Tool name conflict: '{orig_name}' from server '{client.name}' "
                            f"already exists. Renamed to '{target_name}'."
                        )

                    seen_names.add(target_name)

                    description = t.description or f"MCP tool from server '{client.name}'"
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
            except Exception as e:
                logger.error(f"Failed to retrieve tools from connected MCP server '{client.name}': {e}")

        return mcp_tools

    async def disconnect_all(self) -> None:
        """Gracefully disconnects all running MCP servers."""
        if not self.clients:
            return

        logger.info("Disconnecting all active MCP servers...")
        for name, client in list(self.clients.items()):
            try:
                await client.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting from MCP server '{name}': {e}")
        self.clients.clear()
