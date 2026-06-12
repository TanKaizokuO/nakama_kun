"""tools/core/write_file.py — WriteFileTool implementation."""

from __future__ import annotations

import os
from typing import Any

from nakama_kun.tools.interfaces import BaseTool, ToolResult
from nakama_kun.tools.safety import assert_within_workspace


class WriteFileTool(BaseTool):
    """Write text content to a file within the workspace."""

    name = "write_file"
    description = (
        "Write text content to a file at the given path. "
        "Creates parent directories if they do not exist. "
        "Overwrites the file if it already exists. "
        "The path must be within the workspace root."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Destination file path (relative or absolute within workspace).",
            },
            "content": {
                "type": "string",
                "description": "Text content to write to the file.",
            },
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        workspace_root: str | None = None,
        safety_manager: Any = None,
        approval_provider: Any = None,
    ) -> None:
        self._workspace_root = workspace_root or os.getcwd()
        self.safety_manager = safety_manager
        self.approval_provider = approval_provider

    async def execute(self, **kwargs: Any) -> ToolResult:  # noqa: ANN401
        path: str = kwargs.get("path", "")
        content: str = kwargs.get("content", "")
        if not path:
            return ToolResult(success=False, error="'path' argument is required.")
        try:
            if self.safety_manager is not None and self.approval_provider is not None:
                # Route through safety manager
                proposal = self.safety_manager.propose_change(path, content)
                applied = await self.safety_manager.apply_proposal(proposal, self.approval_provider)
                if not applied:
                    return ToolResult(
                        success=False,
                        error=f"File write to '{path}' was rejected by the user.",
                    )
                return ToolResult(
                    success=True,
                    output=f"Successfully wrote {len(content)} characters to '{proposal.file_path}' after approval.",
                )

            # Fallback to direct write
            safe_path = assert_within_workspace(path, self._workspace_root)
            safe_path.parent.mkdir(parents=True, exist_ok=True)
            safe_path.write_text(content, encoding="utf-8")
            return ToolResult(
                success=True,
                output=f"Successfully wrote {len(content)} characters to '{safe_path}'.",
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
