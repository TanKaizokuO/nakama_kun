"""tools/core/search_files.py — SearchFilesTool implementation (pure-Python grep)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from nakama_kun.tools.interfaces import BaseTool, ToolResult
from nakama_kun.tools.safety import assert_within_workspace

# Hard cap on matches returned to avoid flooding the context window.
_MAX_MATCHES = 50


class SearchFilesTool(BaseTool):
    """Search for a text pattern across files in the workspace."""

    name = "search_files"
    description = (
        "Search for a text query (regex-capable) across all text files in the given "
        "directory (recursive). Returns matching lines with file paths and line numbers. "
        "Limited to the first 50 matches."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Text or regex pattern to search for.",
            },
            "path": {
                "type": "string",
                "description": (
                    "Directory to search within (relative or absolute within workspace). "
                    "Defaults to '.' (workspace root)."
                ),
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    # File extensions that are treated as binary and skipped.
    _SKIP_SUFFIXES: frozenset[str] = frozenset(
        {
            ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
            ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z",
            ".exe", ".bin", ".so", ".dylib", ".dll", ".whl", ".pyc",
            ".lock",
        }
    )

    def __init__(self, workspace_root: str | None = None) -> None:
        self._workspace_root = workspace_root or os.getcwd()

    async def execute(self, **kwargs: Any) -> ToolResult:  # noqa: ANN401
        query: str = kwargs.get("query", "")
        path_str: str = kwargs.get("path", ".")

        if not query:
            return ToolResult(success=False, error="'query' argument is required.")

        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error as exc:
            return ToolResult(success=False, error=f"Invalid regex pattern: {exc}")

        try:
            # Resolve relative paths against workspace_root, not the process cwd
            if not Path(path_str).is_absolute():
                resolved_input = Path(self._workspace_root) / path_str
            else:
                resolved_input = Path(path_str)

            safe_dir = assert_within_workspace(resolved_input, self._workspace_root)
            if not safe_dir.is_dir():
                return ToolResult(
                    success=False,
                    error=f"'{safe_dir}' is not a directory or does not exist.",
                )

            root = Path(self._workspace_root).resolve()
            matches: list[str] = []

            for file_path in sorted(safe_dir.rglob("*")):
                if not file_path.is_file():
                    continue
                if file_path.suffix.lower() in self._SKIP_SUFFIXES:
                    continue
                # Skip hidden dirs / venv / cache dirs
                if any(
                    part.startswith(".") or part in {"__pycache__", ".venv", "node_modules"}
                    for part in file_path.parts
                ):
                    continue

                try:
                    text = file_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue

                for lineno, line in enumerate(text.splitlines(), start=1):
                    if pattern.search(line):
                        rel = file_path.relative_to(root)
                        matches.append(f"{rel}:{lineno}: {line.rstrip()}")
                        if len(matches) >= _MAX_MATCHES:
                            break

                if len(matches) >= _MAX_MATCHES:
                    break

            if not matches:
                return ToolResult(
                    success=True, output=f"No matches found for '{query}'."
                )

            header = f"Found {len(matches)} match(es) for '{query}':"
            if len(matches) == _MAX_MATCHES:
                header += f" (showing first {_MAX_MATCHES})"

            return ToolResult(success=True, output=header + "\n" + "\n".join(matches))
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
