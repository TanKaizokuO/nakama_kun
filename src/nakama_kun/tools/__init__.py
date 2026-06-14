"""
tools/__init__.py — Public API for the nakama_kun tool layer.

Convenience factory ``build_default_registry`` builds and returns a
``ToolRegistry`` pre-loaded with all five core workspace tools, using the
supplied (or inferred) workspace root.
"""

from __future__ import annotations

import os
from typing import Any

from nakama_kun.tools.core import (
    ListFilesTool,
    ReadFileTool,
    RunCommandTool,
    SearchFilesTool,
    SearchVectorStoreTool,
    WriteFileTool,
)
from nakama_kun.tools.exceptions import (
    CommandTimeoutError,
    PathEscapeError,
    ToolError,
    UnknownToolError,
)
from nakama_kun.tools.interfaces import BaseTool, ToolResult, UnifiedTool
from nakama_kun.tools.adapters import MCPToolAdapter
from nakama_kun.tools.discovery import ToolDiscoveryService
from nakama_kun.tools.registry import ToolRegistry
from nakama_kun.tools.router import ToolRouter
from nakama_kun.tools.safety import assert_within_workspace


def build_default_registry(
    workspace_root: str | None = None,
    safety_manager: Any = None,
    approval_provider: Any = None,
    mcp_tools: list[BaseTool] | None = None,
) -> ToolRegistry:
    """Create a :class:`ToolRegistry` loaded with all core workspace tools.

    Args:
        workspace_root: Absolute path to the workspace root.  Defaults to
            ``os.getcwd()`` if not provided.
        safety_manager: SafetyManager to proposal checks.
        approval_provider: ApprovalProvider to request user confirms.
        mcp_tools: Optional list of MCP tools to register.

    Returns:
        A fully-populated :class:`ToolRegistry`.
    """
    root = workspace_root or os.getcwd()
    registry = ToolRegistry()
    registry.register(ReadFileTool(root))
    registry.register(
        WriteFileTool(
            root, safety_manager=safety_manager, approval_provider=approval_provider
        )
    )
    registry.register(ListFilesTool(root))
    registry.register(SearchFilesTool(root))
    registry.register(SearchVectorStoreTool(root))
    registry.register(RunCommandTool(cwd=root))
    if mcp_tools:
        for tool in mcp_tools:
            registry.register(tool)
    return registry


__all__ = [
    # factory
    "build_default_registry",
    # classes
    "BaseTool",
    "UnifiedTool",
    "MCPToolAdapter",
    "ToolDiscoveryService",
    "ToolResult",
    "ToolRegistry",
    "ToolRouter",
    # core tools
    "ReadFileTool",
    "WriteFileTool",
    "ListFilesTool",
    "SearchFilesTool",
    "SearchVectorStoreTool",
    "RunCommandTool",
    # exceptions
    "ToolError",
    "PathEscapeError",
    "CommandTimeoutError",
    "UnknownToolError",
    # safety
    "assert_within_workspace",
]
