"""
tools/router.py — Dispatches LLM tool calls to registered tool implementations.

The router receives a tool name and a dict of arguments parsed from the LLM
response, looks up the tool in the registry, and runs it.  Provider-level
payload shapes never reach this layer — callers pass plain Python values.
"""

from __future__ import annotations

import json
import os
from typing import Any

from loguru import logger

from nakama_kun.tools.interfaces import ToolResult
from nakama_kun.tools.registry import ToolRegistry
from nakama_kun.tools.safety import assert_within_workspace


import json
import re
from typing import Any

from loguru import logger

from nakama_kun.tools.interfaces import ToolResult
from nakama_kun.tools.registry import ToolRegistry


def is_mutating_command(cmd: str) -> str | None:
    # Clean cmd: replace multiple spaces with single space, strip
    cmd_clean = " ".join(cmd.split()).lower()
    
    # 1. Package Installation
    install_patterns = [
        r"\bpip(3)?\s+(install|upgrade|uninstall)\b",
        r"\bnpm\s+(install|i|add|update|upgrade|uninstall|remove|rm)\b",
        r"\byarn\s+(add|install|upgrade|remove)\b",
        r"\bpnpm\s+(add|install|update|upgrade|remove|rm)\b",
        r"\bpoetry\s+(add|install|update|remove)\b",
        r"\bapt(-get)?\s+(install|upgrade|remove|purge|autoremove)\b",
        r"\bpipenv\s+(install|add|uninstall)\b",
        r"\bcargo\s+(install|add|rm)\b",
        r"\bgem\s+(install|uninstall)\b",
    ]
    for pattern in install_patterns:
        if re.search(pattern, cmd_clean):
            return "installing packages"

    # 2. Git operations (mutating)
    git_patterns = [
        r"\bgit\s+(add|commit|push|pull|checkout|clone|merge|rebase|reset|revert|init|rm|mv|branch)\b",
    ]
    for pattern in git_patterns:
        if re.search(pattern, cmd_clean):
            return "git operations"

    # 3. mkdir
    if re.search(r"\bmkdir\b", cmd_clean):
        return "mkdir"

    # 4. Source modifications / File creation / deletion / modifications
    mod_commands = [
        r"\btouch\b",
        r"\brm\b",
        r"\bmv\b",
        r"\bcp\b",
        r"\bln\b",
        r"\bchmod\b",
        r"\bchown\b",
        r"\btee\b",
        r"\bsed\b",
    ]
    for cmd_pattern in mod_commands:
        if re.search(cmd_pattern, cmd_clean):
            return f"source modifications ({cmd_pattern.strip(r'\b')})"
            
    # Redirection to a file: > or >> (excluding stderr 2>, 2>&1, etc.)
    if re.search(r"(?<!2)>>?(?!\s*&)", cmd_clean) or "&>" in cmd_clean:
        return "source modifications (redirection)"

    return None


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
        self.violations: list[dict[str, Any]] = []

    async def dispatch(
        self,
        name: str,
        arguments: dict[str, Any] | str,
        task_type: str | None = None,
    ) -> ToolResult:
        """Look up *name* in the registry and call ``execute(**arguments)``.

        Args:
            name: The tool name as returned by the LLM.
            arguments: Keyword arguments for the tool — either a pre-parsed
                dict or a JSON string (as some providers return raw strings).
            task_type: The orchestrator's task_type context to enforce safety.

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

        # Retrieval Safety Enforcement
        if task_type == "RETRIEVAL":
            blocked_tool_names = {"write_file", "create_file", "delete_file", "mkdir", "replace_file_content", "multi_replace_file_content"}
            is_blocked_name = (
                name in blocked_tool_names 
                or name.startswith("write_") 
                or name.startswith("create_") 
                or name.startswith("delete_") 
                or name.startswith("modify_")
            )
            
            reason = None
            if is_blocked_name:
                reason = f"Blocked: Write/modify operations are prohibited in RETRIEVAL tasks. Tool '{name}' is blocked."
            elif name == "run_command":
                cmd = parsed_args.get("cmd", "")
                reason_detail = is_mutating_command(cmd)
                if reason_detail:
                    reason = f"Blocked: {reason_detail} is prohibited in RETRIEVAL tasks. Command: '{cmd}'"
                    
            if reason:
                violation = {
                    "tool": name,
                    "arguments": parsed_args,
                    "reason": reason,
                }
                self.violations.append(violation)
                logger.warning(f"RETRIEVAL VIOLATION: {reason}")
                return ToolResult(success=False, error=reason)

        # Resolve path and workspace_root for diagnostic logging
        workspace_root = "N/A"
        if hasattr(tool, "_workspace_root") and tool._workspace_root:
            workspace_root = str(tool._workspace_root)
        elif hasattr(tool, "cwd") and tool.cwd:
            workspace_root = str(tool.cwd)

        resolved_path = "N/A"
        path_arg = parsed_args.get("path")
        if path_arg:
            try:
                resolved_path = str(assert_within_workspace(path_arg, workspace_root if workspace_root != "N/A" else os.getcwd()))
            except Exception as e:
                resolved_path = f"Error resolving path: {e}"

        logger.info(
            f"Requested tool: {name}\n"
            f"Resolved tool: {tool.__class__.__name__}\n"
            f"Arguments: {parsed_args}\n"
            f"Workspace root: {workspace_root}\n"
            f"Resolved path: {resolved_path}"
        )

        try:
            result = await tool.execute(**parsed_args)
            exception_info = "None"
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Tool '{name}' raised an unexpected error: {exc}")
            result = ToolResult(success=False, error=str(exc))
            exception_info = str(exc)

        success_status = "Success" if result.success else "Failure"
        if not result.success and exception_info == "None":
            exception_info = result.error or "Unknown error"
        
        payload_info = result.output if result.success else "None"

        logger.info(
            f"Success/Failure: {success_status}\n"
            f"Exception: {exception_info}\n"
            f"Return payload: {payload_info}"
        )
        return result
