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
    WriteFileTool,
)
from nakama_kun.tools.exceptions import (
    CommandTimeoutError,
    PathEscapeError,
    ToolError,
    UnknownToolError,
)
from nakama_kun.tools.interfaces import BaseTool, ToolResult
from nakama_kun.tools.registry import ToolRegistry
from nakama_kun.tools.router import ToolRouter
from nakama_kun.tools.safety import assert_within_workspace


def build_default_registry(
    workspace_root: str | None = None,
    safety_manager: Any = None,
    approval_provider: Any = None,
) -> ToolRegistry:
    """Create a :class:`ToolRegistry` loaded with all core workspace tools.

    Args:
        workspace_root: Absolute path to the workspace root.  Defaults to
            ``os.getcwd()`` if not provided.
        safety_manager: SafetyManager to proposal checks.
        approval_provider: ApprovalProvider to request user confirms.

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
    registry.register(RunCommandTool(cwd=root))
    return registry


__all__ = [
    # factory
    "build_default_registry",
    # classes
    "BaseTool",
    "ToolResult",
    "ToolRegistry",
    "ToolRouter",
    # core tools
    "ReadFileTool",
    "WriteFileTool",
    "ListFilesTool",
    "SearchFilesTool",
    "RunCommandTool",
    # exceptions
    "ToolError",
    "PathEscapeError",
    "CommandTimeoutError",
    "UnknownToolError",
    # safety
    "assert_within_workspace",
]
