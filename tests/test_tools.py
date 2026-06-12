"""
tests/test_tools.py — Unit tests for the nakama_kun tools package.

Covers:
  - Path safety: assert_within_workspace raises on escape, passes on safe paths.
  - ReadFileTool: reads existing files, rejects missing files and path escapes.
  - WriteFileTool: creates files, creates parent dirs, rejects path escapes.
  - ListFilesTool: lists a temp directory, rejects non-directories.
  - SearchFilesTool: finds matches, returns no-match message, handles bad regex.
  - RunCommandTool: success, non-zero exit, timeout guardrail.
  - ToolRegistry: register / get / all_schemas / UnknownToolError.
  - ToolRouter: dispatches correctly, raises UnknownToolError on unknown name.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from nakama_kun.tools.core.list_files import ListFilesTool
from nakama_kun.tools.core.read_file import ReadFileTool
from nakama_kun.tools.core.run_command import RunCommandTool
from nakama_kun.tools.core.search_files import SearchFilesTool
from nakama_kun.tools.core.write_file import WriteFileTool
from nakama_kun.tools.exceptions import (
    CommandTimeoutError,
    PathEscapeError,
    UnknownToolError,
)
from nakama_kun.tools.interfaces import BaseTool, ToolResult
from nakama_kun.tools.registry import ToolRegistry
from nakama_kun.tools.router import ToolRouter
from nakama_kun.tools.safety import assert_within_workspace

# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


class TestAssertWithinWorkspace:
    def test_safe_child_path_is_returned(self, tmp_path: Path) -> None:
        child = tmp_path / "src" / "main.py"
        result = assert_within_workspace(child, tmp_path)
        assert result == child.resolve()

    def test_workspace_root_itself_is_allowed(self, tmp_path: Path) -> None:
        result = assert_within_workspace(tmp_path, tmp_path)
        assert result == tmp_path.resolve()

    def test_escape_via_dotdot_raises(self, tmp_path: Path) -> None:
        escaped = tmp_path / ".." / "outside.txt"
        with pytest.raises(PathEscapeError, match="outside the workspace root"):
            assert_within_workspace(escaped, tmp_path)

    def test_absolute_escape_raises(self, tmp_path: Path) -> None:
        with pytest.raises(PathEscapeError):
            assert_within_workspace("/etc/passwd", tmp_path)


# ---------------------------------------------------------------------------
# ReadFileTool
# ---------------------------------------------------------------------------


class TestReadFileTool:
    def test_reads_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "hello.txt"
        target.write_text("hello, world", encoding="utf-8")
        tool = ReadFileTool(str(tmp_path))
        result = tool.execute(path=str(target))
        assert result.success
        assert result.output == "hello, world"

    def test_missing_file_returns_error(self, tmp_path: Path) -> None:
        tool = ReadFileTool(str(tmp_path))
        result = tool.execute(path=str(tmp_path / "ghost.txt"))
        assert not result.success
        assert result.error is not None

    def test_path_escape_returns_error(self, tmp_path: Path) -> None:
        tool = ReadFileTool(str(tmp_path))
        result = tool.execute(path="/etc/passwd")
        assert not result.success
        assert "outside" in (result.error or "").lower()

    def test_missing_path_arg_returns_error(self, tmp_path: Path) -> None:
        tool = ReadFileTool(str(tmp_path))
        result = tool.execute()
        assert not result.success


# ---------------------------------------------------------------------------
# WriteFileTool
# ---------------------------------------------------------------------------


class TestWriteFileTool:
    def test_writes_new_file(self, tmp_path: Path) -> None:
        tool = WriteFileTool(str(tmp_path))
        target = tmp_path / "output.txt"
        result = tool.execute(path=str(target), content="nakama!")
        assert result.success
        assert target.read_text() == "nakama!"

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        tool = WriteFileTool(str(tmp_path))
        target = tmp_path / "a" / "b" / "c.txt"
        result = tool.execute(path=str(target), content="deep")
        assert result.success
        assert target.exists()

    def test_path_escape_returns_error(self, tmp_path: Path) -> None:
        tool = WriteFileTool(str(tmp_path))
        result = tool.execute(path="/etc/hacked.txt", content="x")
        assert not result.success

    def test_missing_path_returns_error(self, tmp_path: Path) -> None:
        tool = WriteFileTool(str(tmp_path))
        result = tool.execute(content="no path")
        assert not result.success


# ---------------------------------------------------------------------------
# ListFilesTool
# ---------------------------------------------------------------------------


class TestListFilesTool:
    def test_lists_directory(self, tmp_path: Path) -> None:
        (tmp_path / "alpha.py").write_text("", encoding="utf-8")
        (tmp_path / "subdir").mkdir()
        tool = ListFilesTool(str(tmp_path))
        result = tool.execute(path=str(tmp_path))
        assert result.success
        assert "alpha.py" in (result.output or "")
        assert "subdir" in (result.output or "")

    def test_empty_directory(self, tmp_path: Path) -> None:
        tool = ListFilesTool(str(tmp_path))
        result = tool.execute(path=str(tmp_path))
        assert result.success
        assert "empty" in (result.output or "").lower()

    def test_non_directory_returns_error(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("x")
        tool = ListFilesTool(str(tmp_path))
        result = tool.execute(path=str(f))
        assert not result.success

    def test_defaults_to_workspace_root(self, tmp_path: Path) -> None:
        (tmp_path / "readme.md").write_text("hello")
        tool = ListFilesTool(str(tmp_path))
        result = tool.execute()  # no path argument
        assert result.success
        assert "readme.md" in (result.output or "")


# ---------------------------------------------------------------------------
# SearchFilesTool
# ---------------------------------------------------------------------------


class TestSearchFilesTool:
    def test_finds_matching_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("def hello():\n    pass\n", encoding="utf-8")
        tool = SearchFilesTool(str(tmp_path))
        result = tool.execute(query="def hello")
        assert result.success
        assert "code.py" in (result.output or "")
        assert "def hello" in (result.output or "")

    def test_no_match_returns_success_with_message(self, tmp_path: Path) -> None:
        (tmp_path / "empty.py").write_text("", encoding="utf-8")
        tool = SearchFilesTool(str(tmp_path))
        result = tool.execute(query="xyz_does_not_exist_abc")
        assert result.success
        assert "no matches" in (result.output or "").lower()

    def test_invalid_regex_returns_error(self, tmp_path: Path) -> None:
        tool = SearchFilesTool(str(tmp_path))
        result = tool.execute(query="[invalid regex")
        assert not result.success
        assert "regex" in (result.error or "").lower()

    def test_missing_query_returns_error(self, tmp_path: Path) -> None:
        tool = SearchFilesTool(str(tmp_path))
        result = tool.execute()
        assert not result.success


# ---------------------------------------------------------------------------
# RunCommandTool
# ---------------------------------------------------------------------------


class TestRunCommandTool:
    def test_successful_command(self, tmp_path: Path) -> None:
        tool = RunCommandTool(cwd=str(tmp_path))
        result = tool.execute(cmd="echo hello")
        assert result.success
        assert "hello" in (result.output or "")

    def test_failing_command(self, tmp_path: Path) -> None:
        tool = RunCommandTool(cwd=str(tmp_path))
        result = tool.execute(cmd="exit 42")
        assert not result.success
        assert "42" in (result.output or "")

    def test_timeout_raises_command_timeout_error(self, tmp_path: Path) -> None:
        tool = RunCommandTool(cwd=str(tmp_path))
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="sleep 99", timeout=1)
            with pytest.raises(CommandTimeoutError):
                tool.execute(cmd="sleep 99", timeout=1)

    def test_missing_cmd_returns_error(self, tmp_path: Path) -> None:
        tool = RunCommandTool(cwd=str(tmp_path))
        result = tool.execute()
        assert not result.success


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------


class _DummyTool(BaseTool):
    name = "dummy"
    description = "A dummy test tool."
    parameters: dict = {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, output="dummy result")


class TestToolRegistry:
    def test_register_and_get(self) -> None:
        registry = ToolRegistry()
        tool = _DummyTool()
        registry.register(tool)
        assert registry.get("dummy") is tool

    def test_get_unknown_raises(self) -> None:
        registry = ToolRegistry()
        with pytest.raises(UnknownToolError, match="No tool named"):
            registry.get("nonexistent")

    def test_all_schemas_returns_list(self) -> None:
        registry = ToolRegistry()
        registry.register(_DummyTool())
        schemas = registry.all_schemas()
        assert len(schemas) == 1
        assert schemas[0]["type"] == "function"
        assert schemas[0]["function"]["name"] == "dummy"

    def test_names_sorted(self) -> None:
        registry = ToolRegistry()

        class ToolZ(BaseTool):
            name = "z_tool"
            description = ""
            parameters: dict = {"type": "object", "properties": {}, "required": []}

            def execute(self, **kwargs: object) -> ToolResult:
                return ToolResult(success=True)

        registry.register(_DummyTool())
        registry.register(ToolZ())
        assert registry.names() == ["dummy", "z_tool"]

    def test_len(self) -> None:
        registry = ToolRegistry()
        assert len(registry) == 0
        registry.register(_DummyTool())
        assert len(registry) == 1

    def test_register_overwrites_silently(self) -> None:
        registry = ToolRegistry()
        registry.register(_DummyTool())
        registry.register(_DummyTool())  # no error
        assert len(registry) == 1


# ---------------------------------------------------------------------------
# ToolRouter
# ---------------------------------------------------------------------------


class TestToolRouter:
    def test_dispatches_known_tool(self) -> None:
        registry = ToolRegistry()
        registry.register(_DummyTool())
        router = ToolRouter(registry)
        result = router.dispatch("dummy", {})
        assert result.success
        assert result.output == "dummy result"

    def test_dispatches_with_json_string_args(self) -> None:
        registry = ToolRegistry()
        registry.register(_DummyTool())
        router = ToolRouter(registry)
        result = router.dispatch("dummy", '{"key": "value"}')
        assert result.success

    def test_unknown_tool_raises(self) -> None:
        registry = ToolRegistry()
        router = ToolRouter(registry)
        with pytest.raises(UnknownToolError):
            router.dispatch("unknown_tool", {})

    def test_tool_exception_returns_error_result(self) -> None:
        """If a tool raises unexpectedly, the router returns a ToolResult with success=False."""

        class BrokenTool(BaseTool):
            name = "broken"
            description = "always raises"
            parameters: dict = {"type": "object", "properties": {}, "required": []}

            def execute(self, **kwargs: object) -> ToolResult:
                raise RuntimeError("internal boom")

        registry = ToolRegistry()
        registry.register(BrokenTool())
        router = ToolRouter(registry)
        result = router.dispatch("broken", {})
        assert not result.success
        assert "internal boom" in (result.error or "")
