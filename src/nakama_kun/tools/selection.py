from __future__ import annotations

from typing import Any
from loguru import logger


class ToolSelectionLayer:
    """Intelligently routes, overrides, and filters tool calls during execution.

    Responsibilities:
    - Choose the best tool.
    - Avoid redundant tool calls (checking recent execution history).
    - Prefer local tools when appropriate (e.g. redirecting filesystem operations to local tools).
    """

    def __init__(self, history: list[dict[str, Any]] | None = None) -> None:
        self.history = history or []

    def filter_and_optimize(
        self, name: str, arguments: dict[str, Any]
    ) -> tuple[str, dict[str, Any], str | None]:
        """Inspects a proposed tool call.

        Returns:
            A tuple of (final_tool_name, final_arguments, block_reason_if_any).
        """
        # 1. Avoid redundant tools
        # If the exact same tool with the exact same arguments succeeded recently,
        # we can flag it as redundant.
        for entry in reversed(self.history):
            if (
                entry.get("tool") == name
                and entry.get("arguments") == arguments
                and entry.get("success", False)
            ):
                # Block redundant read/exploration/query calls
                redundant_blocklist = [
                    "read_file",
                    "list_directory",
                    "list_files",
                    "search_files",
                    "postgres_list_tables",
                    "browser_extract_content",
                ]
                is_redundant_name = (
                    name in redundant_blocklist
                    or name.startswith("github_get_")
                    or name.startswith("github_list_")
                )
                if is_redundant_name:
                    return (
                        name,
                        arguments,
                        f"Redundant tool call blocked: '{name}' with args {arguments} already succeeded in this execution loop.",
                    )

        # 2. Prefer local tools when appropriate
        # E.g. if the tool is filesystem-related and targets a local workspace file,
        # redirect to local tools (read_file, write_file, list_files)
        local_mapping = {
            "mcp_filesystem_read_file": "read_file",
            "mcp_filesystem_write_file": "write_file",
            "mcp_filesystem_list_directory": "list_files",
            "mcp_filesystem_search_files": "search_files",
            "filesystem_read_file": "read_file",
            "filesystem_write_file": "write_file",
            "filesystem_list_directory": "list_files",
            "filesystem_search_files": "search_files",
        }

        if name in local_mapping:
            target_local = local_mapping[name]
            logger.info(f"[ToolSelection] Redirecting MCP tool '{name}' to local tool '{target_local}'")
            return target_local, arguments, None

        return name, arguments, None
