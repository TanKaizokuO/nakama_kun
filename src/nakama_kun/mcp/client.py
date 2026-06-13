from __future__ import annotations

import contextlib
import os
from typing import Any

from loguru import logger
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, Tool


class MCPClient:
    """Client wrapper managing the stdio lifecycle and session for an MCP server."""

    def __init__(
        self,
        name: str,
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self.command = command
        self.args = args
        self.env = env
        self.session: ClientSession | None = None
        self._exit_stack: contextlib.AsyncExitStack | None = None

    async def connect(self) -> None:
        """Launches the stdio MCP server process and initializes a ClientSession."""
        if self.session is not None:
            return

        # Build merged environment variables
        merged_env = os.environ.copy()
        if self.env:
            merged_env.update(self.env)

        logger.info(f"Connecting to MCP server '{self.name}' via stdio (command: {self.command})")

        server_params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=merged_env,
        )

        self._exit_stack = contextlib.AsyncExitStack()
        try:
            read, write = await self._exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            session = await self._exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            await session.initialize()
            self.session = session
            logger.info(f"Connected to MCP server '{self.name}' successfully.")
        except Exception as e:
            logger.error(f"Failed to connect to MCP server '{self.name}': {e}")
            await self.disconnect()
            raise e

    async def disconnect(self) -> None:
        """Gracefully shuts down the connection and stops the server process."""
        if self._exit_stack is not None:
            logger.info(f"Disconnecting from MCP server '{self.name}'...")
            try:
                await self._exit_stack.aclose()
            except Exception as e:
                logger.warning(f"Error during disconnect cleanup for '{self.name}': {e}")
        self._exit_stack = None
        self.session = None

    async def list_tools(self) -> list[Tool]:
        """Lists all tools exposed by the MCP server."""
        if self.session is None:
            raise RuntimeError(f"MCP client '{self.name}' is not connected.")
        try:
            result = await self.session.list_tools()
            return list(result.tools)
        except Exception as e:
            logger.error(f"Failed to list tools for MCP server '{self.name}': {e}")
            raise e

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> CallToolResult:
        """Invokes a tool on the MCP server."""
        if self.session is None:
            raise RuntimeError(f"MCP client '{self.name}' is not connected.")
        try:
            return await self.session.call_tool(tool_name, arguments)
        except Exception as e:
            logger.error(f"Failed to call tool '{tool_name}' on MCP server '{self.name}': {e}")
            raise e
