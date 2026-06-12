"""tools/core/list_files.py — ListFilesTool implementation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from nakama_kun.tools.interfaces import BaseTool, ToolResult
from nakama_kun.tools.safety import assert_within_workspace


class ListFilesTool(BaseTool):
    """List files and directories at a given workspace path."""

    name = "list_files"
    description = (
        "List the files and subdirectories at the given path. "
        "Returns a formatted directory listing. "
        "Defaults to the workspace root if no path is specified."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Directory path to list (relative or absolute within workspace). "
                    "Defaults to '.' (workspace root)."
                ),
            }
        },
        "required": [],
        "additionalProperties": False,
    }

    def __init__(self, workspace_root: str | None = None) -> None:
        self._workspace_root = workspace_root or os.getcwd()

    async def execute(self, **kwargs: Any) -> ToolResult:  # noqa: ANN401
        path_str: str = kwargs.get("path", ".")
        # Resolve relative paths against workspace_root, not the process cwd
        if not Path(path_str).is_absolute():
            resolved_input = Path(self._workspace_root) / path_str
        else:
            resolved_input = Path(path_str)

        try:
            safe_path = assert_within_workspace(resolved_input, self._workspace_root)
            if not safe_path.is_dir():
                return ToolResult(
                    success=False,
                    error=f"'{safe_path}' is not a directory or does not exist.",
                )

            entries = sorted(safe_path.iterdir(), key=lambda p: (p.is_file(), p.name))
            lines: list[str] = [f"Contents of '{safe_path}':"]
            for entry in entries:
                rel = entry.relative_to(Path(self._workspace_root).resolve())
                kind = "[dir] " if entry.is_dir() else "[file]"
                lines.append(f"  {kind} {rel}")

            if not entries:
                lines.append("  (empty directory)")

            return ToolResult(success=True, output="\n".join(lines))
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
