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


def _invalid_arguments(message: str, expected: dict[str, Any] | None = None) -> ToolResult:
    expected_text = ""
    if expected:
        try:
            expected_text = "\n\nExpected:\n" + json.dumps(expected, indent=2)
        except TypeError:
            expected_text = f"\n\nExpected:\n{expected}"
    return ToolResult(
        success=False,
        error=(
            "INVALID_ARGUMENTS\n\n"
            "Tool call rejected.\n\n"
            f"Reason:\n{message}"
            f"{expected_text}\n\n"
            "Re-issue the tool call with valid JSON."
        ),
    )


def _schema_type_matches(value: Any, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return (isinstance(value, int | float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "object":
        return isinstance(value, dict)
    return True


def _validate_arguments_schema(arguments: dict[str, Any], schema: dict[str, Any]) -> str | None:
    required = schema.get("required", [])
    for name in required:
        if name not in arguments:
            return f"Missing required argument: {name}"

    properties = schema.get("properties", {})
    for name, value in arguments.items():
        prop_schema = properties.get(name)
        if not isinstance(prop_schema, dict):
            continue
        expected_type = prop_schema.get("type")
        if isinstance(expected_type, list):
            if not any(_schema_type_matches(value, t) for t in expected_type):
                return f"Argument '{name}' has invalid type."
        elif isinstance(expected_type, str) and not _schema_type_matches(value, expected_type):
            return f"Argument '{name}' must be of type {expected_type}."
    return None


class ToolRouter:
    """Dispatches tool calls to the correct ``BaseTool`` implementation."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def dispatch(self, name: str, arguments: dict[str, Any] | str) -> ToolResult:
        """Look up *name* in the registry and call ``execute(**arguments)``.

        Args:
            name: The tool name as returned by the LLM.
            arguments: Keyword arguments for the tool — either a pre-parsed
                dict or a JSON string (as some providers return raw strings).

        Returns:
            A :class:`~nakama_kun.tools.interfaces.ToolResult`.
        """
        tool = self._registry.get(name)  # raises UnknownToolError if missing
        schema = tool.parameters

        # Normalise arguments: some providers return a JSON string.
        # Invalid JSON is a tool-call failure, not an invitation to run with {}.
        parsed_args: dict[str, Any]
        if isinstance(arguments, str):
            try:
                raw_args = json.loads(arguments)
            except json.JSONDecodeError as exc:
                logger.warning(f"Tool '{name}': failed to parse arguments JSON: {exc}")
                return _invalid_arguments("Malformed JSON arguments.", schema)
            if not isinstance(raw_args, dict):
                return _invalid_arguments("Tool arguments must be a JSON object.", schema)
            parsed_args = raw_args
        elif isinstance(arguments, dict):
            parsed_args = arguments
        else:
            return _invalid_arguments("Tool arguments must be a JSON object.", schema)

        schema_error = _validate_arguments_schema(parsed_args, schema)
        if schema_error:
            return _invalid_arguments(schema_error, schema)

        logger.debug(f"ToolRouter dispatching '{name}' with args={parsed_args}")

        try:
            result = await tool.execute(**parsed_args)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Tool '{name}' raised an unexpected error: {exc}")
            result = ToolResult(success=False, error=str(exc))

        logger.debug(
            f"ToolRouter '{name}' → success={result.success}, "
            f"output_len={len(result.output or '')}"
        )
        return result
