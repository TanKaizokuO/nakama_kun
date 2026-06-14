from __future__ import annotations

import os
from typing import Any
from loguru import logger


class MCPSafetyControls:
    """Enforces safety policies, access controls, and read-only modes on MCP tools."""

    _instance: MCPSafetyControls | None = None

    @classmethod
    def get_instance(cls) -> MCPSafetyControls:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self.allowed_servers: set[str] | None = None  # None means all allowed
        self.allowed_tools: set[str] | None = None    # None means all allowed
        self.read_only: bool = os.environ.get("MCP_READ_ONLY") == "true"
        self.require_approval_all: bool = os.environ.get("MCP_REQUIRE_APPROVAL_ALL") == "true"

    def reset(self) -> None:
        """Resets safety controls to defaults."""
        self.allowed_servers = None
        self.allowed_tools = None
        self.read_only = os.environ.get("MCP_READ_ONLY") == "true"
        self.require_approval_all = os.environ.get("MCP_REQUIRE_APPROVAL_ALL") == "true"

    def set_allowed_servers(self, servers: list[str] | None) -> None:
        self.allowed_servers = set(servers) if servers is not None else None

    def set_allowed_tools(self, tools: list[str] | None) -> None:
        self.allowed_tools = set(tools) if tools is not None else None

    def set_read_only(self, read_only: bool) -> None:
        self.read_only = read_only

    def set_require_approval_all(self, require_approval: bool) -> None:
        self.require_approval_all = require_approval

    def is_action_allowed(self, server_name: str, tool_name: str, is_mutating: bool) -> tuple[bool, str | None]:
        """Checks if the tool execution is allowed under current safety constraints.

        Returns:
            A tuple of (allowed: bool, reason: str | None).
        """
        # 1. Server-level permissions/allowlist
        if self.allowed_servers is not None and server_name not in self.allowed_servers:
            return False, f"Server '{server_name}' is not in the allowed servers list."

        # 2. Tool allowlist
        if self.allowed_tools is not None and tool_name not in self.allowed_tools:
            return False, f"Tool '{tool_name}' is not in the allowed tools list."

        # 3. Read-only mode
        if self.read_only and is_mutating:
            return False, f"Mutating tool '{tool_name}' is blocked under Read-Only Mode."

        return True, None
