"""tools/core/read_file.py — ReadFileTool implementation."""

from __future__ import annotations

import os
from typing import Any

from nakama_kun.tools.interfaces import BaseTool, ToolResult
from nakama_kun.tools.safety import assert_within_workspace


class ReadFileTool(BaseTool):
    """Read the text content of a file within the workspace."""

    name = "read_file"
    description = (
        "Read the full text content of a file at the given path. "
        "The path must be relative to or within the workspace root."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to read (relative or absolute within workspace).",
            }
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    def __init__(self, workspace_root: str | None = None) -> None:
        self._workspace_root = workspace_root or os.getcwd()

    async def execute(self, **kwargs: Any) -> ToolResult:  # noqa: ANN401
        path: str = kwargs.get("path", "")
        if not path:
            return ToolResult(success=False, error="'path' argument is required.")
        try:
            safe_path = assert_within_workspace(path, self._workspace_root)
            if not safe_path.is_file():
                return ToolResult(
                    success=False, error=f"'{safe_path}' is not a file or does not exist."
                )
            content = safe_path.read_text(encoding="utf-8", errors="replace")
            return ToolResult(success=True, output=content)
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
