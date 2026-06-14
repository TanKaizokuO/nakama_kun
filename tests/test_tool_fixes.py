from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from nakama_kun.tools.core.read_file import ReadFileTool
from nakama_kun.tools.registry import ToolRegistry
from nakama_kun.tools.router import ToolRouter
from nakama_kun.tools.safety import assert_within_workspace
from nakama_kun.tools.exceptions import PathEscapeError
from nakama_kun.mcp.registry import MCPRegistry
from nakama_kun.mcp.tool import MCPTool


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path.resolve()
    (workspace / "src").mkdir(parents=True, exist_ok=True)
    (workspace / "src" / "code.py").write_text("print('hello')", encoding="utf-8")
    (workspace / "config.json").write_text("{}", encoding="utf-8")
    return workspace


def test_assert_within_workspace_relative_and_absolute(temp_workspace: Path):
    root = temp_workspace
    
    # 1. Absolute path inside workspace
    abs_path = root / "src" / "code.py"
    resolved_abs = assert_within_workspace(abs_path, root)
    assert resolved_abs == abs_path
    
    # 2. Relative path inside workspace (even if current working directory is elsewhere)
    old_cwd = os.getcwd()
    try:
        # Move CWD out of workspace to ensure absolute resolution handles relativity relative to workspace root
        os.chdir(os.path.dirname(str(temp_workspace)))
        
        resolved_rel = assert_within_workspace("src/code.py", root)
        assert resolved_rel == abs_path
        
        resolved_nested = assert_within_workspace("config.json", root)
        assert resolved_nested == (root / "config.json")
    finally:
        os.chdir(old_cwd)


def test_assert_within_workspace_boundary_checks(temp_workspace: Path):
    root = temp_workspace
    
    # Escape via double-dots
    with pytest.raises(PathEscapeError):
        assert_within_workspace("../outside.txt", root)
        
    # Absolute path escape
    with pytest.raises(PathEscapeError):
        assert_within_workspace("/etc/passwd", root)


@pytest.mark.anyio
async def test_read_file_tool_relative_and_absolute(temp_workspace: Path):
    tool = ReadFileTool(str(temp_workspace))
    
    # 1. Read absolute path
    result_abs = await tool.execute(path=str(temp_workspace / "src" / "code.py"))
    assert result_abs.success
    assert result_abs.output == "print('hello')"
    
    # 2. Read relative path
    old_cwd = os.getcwd()
    try:
        os.chdir(os.path.dirname(str(temp_workspace)))
        result_rel = await tool.execute(path="src/code.py")
        assert result_rel.success
        assert result_rel.output == "print('hello')"
    finally:
        os.chdir(old_cwd)


def test_registry_prevents_mcp_shadowing():
    registry = ToolRegistry()
    
    built_in = ReadFileTool("/fake/root")
    registry.register(built_in)
    
    class MockMCPTool:
        name = "read_file"
        description = "MCP duplicate tool"
        parameters = {"type": "object", "properties": {}}
        
    mock_mcp_tool = MockMCPTool()
    registry.register(mock_mcp_tool)  # type: ignore
    
    assert registry.get("read_file") is built_in


def test_mcp_conflict_resolution_and_shadow_prevention():
    registry = ToolRegistry()
    built_in = ReadFileTool("/fake/root")
    registry.register(built_in)
    
    mock_mcp_tool = MagicMock(spec=MCPTool)
    mock_mcp_tool.name = "read_file"
    mock_mcp_tool.to_schema.return_value = {"type": "function", "function": {"name": "read_file"}}
    
    with patch.object(MCPRegistry, "get_instance") as mock_inst_getter:
        mock_registry = MagicMock(spec=MCPRegistry)
        mock_registry.list_tools.return_value = [mock_mcp_tool]
        mock_registry.find_tool.return_value = mock_mcp_tool
        mock_inst_getter.return_value = mock_registry
        
        # Registry should resolve the built-in, not the MCP tool
        assert registry.get("read_file") is built_in
        
        # Schemas list should only return one schema for 'read_file'
        schemas = registry.all_schemas()
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "read_file"


@pytest.mark.anyio
async def test_tool_router_logging_diagnostics(temp_workspace: Path):
    from loguru import logger
    
    logs = []
    def custom_sink(msg):
        logs.append(msg.record["message"])
        
    handler_id = logger.add(custom_sink, level="INFO")
    
    try:
        registry = ToolRegistry()
        tool = ReadFileTool(str(temp_workspace))
        registry.register(tool)
        router = ToolRouter(registry)
        
        result = await router.dispatch("read_file", {"path": "src/code.py"})
        assert result.success
        
        log_text = "\n".join(logs)
        assert "Requested tool: read_file" in log_text
        assert "Resolved tool: ReadFileTool" in log_text
        assert f"Workspace root: {temp_workspace}" in log_text
        assert f"Resolved path: {temp_workspace / 'src' / 'code.py'}" in log_text
        
        assert "Success/Failure: Success" in log_text
        assert "Exception: None" in log_text
        assert "Return payload: print('hello')" in log_text
    finally:
        logger.remove(handler_id)
