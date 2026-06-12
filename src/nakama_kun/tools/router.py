"""
tools/router.py — Dispatches LLM tool calls to registered tool implementations.

The router receives a tool name and a dict of arguments parsed from the LLM
response, looks up the tool in the registry, and runs it.  Provider-level
payload shapes never reach this layer — callers pass plain Python values.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from nakama_kun.tools.interfaces import ToolResult
from nakama_kun.tools.registry import ToolRegistry


class ToolRouter:
    """Dispatches tool calls to the correct ``BaseTool`` implementation."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def dispatch(self, name: str, arguments: dict[str, Any] | str) -> ToolResult:
        """Look up *name* in the registry and call ``execute(**arguments)``.

        Args:
            name: The tool name as returned by the LLM.
            arguments: Keyword arguments for the tool — either a pre-parsed
                dict or a JSON string (as some providers return raw strings).

        Returns:
            A :class:`~nakama_kun.tools.interfaces.ToolResult`.
        """
        # Normalise arguments: some providers return a JSON string
        parsed_args: dict[str, Any]
        if isinstance(arguments, str):
            try:
                parsed_args = json.loads(arguments)
            except json.JSONDecodeError as exc:
                logger.warning(f"Tool '{name}': failed to parse arguments JSON: {exc}")
                parsed_args = {}
        else:
            parsed_args = arguments

        logger.debug(f"ToolRouter dispatching '{name}' with args={parsed_args}")
        tool = self._registry.get(name)  # raises UnknownToolError if missing

        try:
            result = tool.execute(**parsed_args)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Tool '{name}' raised an unexpected error: {exc}")
            result = ToolResult(success=False, error=str(exc))

        logger.debug(
            f"ToolRouter '{name}' → success={result.success}, "
            f"output_len={len(result.output or '')}"
        )
        return result
