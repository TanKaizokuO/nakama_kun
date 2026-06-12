"""tools/core/run_command.py — RunCommandTool implementation."""

from __future__ import annotations

import subprocess
from typing import Any

from nakama_kun.tools.exceptions import CommandTimeoutError
from nakama_kun.tools.interfaces import BaseTool, ToolResult

_DEFAULT_TIMEOUT: int = 30  # seconds
_MAX_OUTPUT_CHARS: int = 8_000  # truncate very long outputs


class RunCommandTool(BaseTool):
    """Execute a shell command and capture its output."""

    name = "run_command"
    description = (
        "Execute a shell command and return its stdout, stderr, and exit code. "
        f"Commands time out after {_DEFAULT_TIMEOUT} seconds. "
        "Use with care — prefer file tools for reading/writing."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "cmd": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": (
                    f"Maximum seconds to wait before killing the process "
                    f"(default {_DEFAULT_TIMEOUT})."
                ),
            },
        },
        "required": ["cmd"],
        "additionalProperties": False,
    }

    def __init__(self, cwd: str | None = None) -> None:
        self._cwd = cwd  # None → inherited from the calling process

    async def execute(self, **kwargs: Any) -> ToolResult:  # noqa: ANN401
        cmd: str = kwargs.get("cmd", "")
        timeout: int = int(kwargs.get("timeout", _DEFAULT_TIMEOUT))

        if not cmd:
            return ToolResult(success=False, error="'cmd' argument is required.")

        try:
            result = subprocess.run(
                cmd,
                shell=True,  # noqa: S602
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self._cwd,
            )
        except subprocess.TimeoutExpired as err:
            raise CommandTimeoutError(
                f"Command timed out after {timeout}s: {cmd!r}"
            ) from err
        except Exception as exc:
            return ToolResult(success=False, error=f"Failed to run command: {exc}")

        stdout = result.stdout or ""
        stderr = result.stderr or ""

        # Truncate extremely long output if combined length exceeds _MAX_OUTPUT_CHARS
        if len(stdout) + len(stderr) > _MAX_OUTPUT_CHARS:
            half_max = _MAX_OUTPUT_CHARS // 2
            if len(stdout) > half_max and len(stderr) > half_max:
                stdout = stdout[:half_max] + "\n...[stdout truncated]"
                stderr = stderr[:half_max] + "\n...[stderr truncated]"
            elif len(stdout) > _MAX_OUTPUT_CHARS - len(stderr):
                stdout = stdout[:_MAX_OUTPUT_CHARS - len(stderr)] + "\n...[stdout truncated]"
            elif len(stderr) > _MAX_OUTPUT_CHARS - len(stdout):
                stderr = stderr[:_MAX_OUTPUT_CHARS - len(stdout)] + "\n...[stderr truncated]"

        success = result.returncode == 0

        import json
        response_data = {
            "success": success,
            "exit_code": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }
        json_str = json.dumps(response_data)

        if success:
            return ToolResult(success=True, output=json_str)
        return ToolResult(
            success=False,
            output=json_str,
            error=json_str,
        )
