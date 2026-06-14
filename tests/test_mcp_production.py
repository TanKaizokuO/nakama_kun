from __future__ import annotations

import os
import pytest
from unittest.mock import patch, MagicMock

from nakama_kun.mcp.auth import MCPAuthManager
from nakama_kun.tools import ToolRegistry, ToolRouter

from nakama_kun.mcp.servers.filesystem import mcp as filesystem_mcp
from nakama_kun.mcp.servers.github import mcp as github_mcp
from nakama_kun.mcp.servers.postgres import mcp as postgres_mcp
from nakama_kun.mcp.servers.browser import mcp as browser_mcp


def test_servers_startup_and_declaration() -> None:
    # Verify name declarations
    assert filesystem_mcp.name == "filesystem"
    assert github_mcp.name == "github"
    assert postgres_mcp.name == "postgres"
    assert browser_mcp.name == "browser"

    # Verify that tools are registered
    assert len(filesystem_mcp.tools) >= 4
    assert len(github_mcp.tools) >= 4
    assert len(postgres_mcp.tools) >= 3
    assert len(browser_mcp.tools) >= 3

    # Check filesystem tool names
    fs_tool_names = set(filesystem_mcp.tools.keys())
    assert "read_file" in fs_tool_names
    assert "write_file" in fs_tool_names
    assert "list_directory" in fs_tool_names
    assert "search_files" in fs_tool_names


def test_auth_validation_github() -> None:
    # 1. Missing Token
    with patch.dict(os.environ, {}, clear=True):
        success, msg = MCPAuthManager.validate_connection("github")
        assert success is False
        assert "not set" in msg

    # 2. Mock Token
    with patch.dict(os.environ, {"GITHUB_TOKEN": "mock_token"}):
        success, msg = MCPAuthManager.validate_connection("github")
        assert success is True
        assert "verified successfully" in msg

    # 3. Connection Failure (Real attempt with invalid token)
    with patch.dict(os.environ, {"GITHUB_TOKEN": "invalid_real_token"}):
        success, msg = MCPAuthManager.validate_connection("github")
        assert success is False
        assert "API error" in msg or "connection error" in msg or "Unauthorized" in msg


def test_auth_validation_postgres() -> None:
    # Mock Mode Validation
    with patch.dict(os.environ, {"POSTGRES_MOCK": "true"}):
        success, msg = MCPAuthManager.validate_connection("postgres")
        assert success is True
        assert "SQLite Mode" in msg

    # Non-mock invalid connection
    with patch.dict(os.environ, {"POSTGRES_HOST": "localhost", "POSTGRES_USER": "testuser"}, clear=True):
        success, msg = MCPAuthManager.validate_connection("postgres")
        assert success is False


def test_auth_validation_browser_and_filesystem(tmp_path: Path) -> None:
    # Browser
    with patch.dict(os.environ, {"BROWSER_MOCK": "true"}):
        success, msg = MCPAuthManager.validate_connection("browser")
        assert success is True

    # Filesystem
    with patch.dict(os.environ, {"WORKSPACE_ROOT": str(tmp_path)}):
        success, msg = MCPAuthManager.validate_connection("filesystem")
        assert success is True
        assert "Filesystem access validated" in msg


def test_tool_metadata_docstring_parsing() -> None:
    # Verify the filesystem read_file tool has properties
    read_tool = filesystem_mcp.tools["read_file"]
    desc = read_tool.description
    assert "Read the content" in desc
    assert "Permissions: filesystem_read" in desc

    # Test the adapters parser logic via a mock MCPTool
    from nakama_kun.mcp.tool import MCPTool
    from nakama_kun.tools.adapters import MCPToolAdapter

    mock_client = MagicMock()
    mock_client.name = "mock_server"

    mcp_tool = MCPTool(
        client=mock_client,
        original_name="test_tool",
        name="test_tool",
        description="A test tool.\nPermissions: test_perm\nCategories: test_cat1, test_cat2\nUsage: Perform testing.",
        parameters={},
    )

    adapter = MCPToolAdapter(mcp_tool)
    assert adapter.permissions == ["test_perm"]
    assert adapter.categories == ["test_cat1", "test_cat2"]
    assert adapter.usage_description == "Perform testing."


def test_tool_executions_mock_mode(tmp_path: Path) -> None:
    # 1. Filesystem read/write execution
    test_file = os.path.join(str(tmp_path), "test.txt")
    write_func = filesystem_mcp.tools["write_file"].fn
    read_func = filesystem_mcp.tools["read_file"].fn

    w_res = write_func(test_file, "hello filesystem")
    assert "written successfully" in w_res

    r_res = read_func(test_file)
    assert r_res == "hello filesystem"

    # 2. GitHub Mock Execution
    with patch.dict(os.environ, {"GITHUB_TOKEN": "mock_token"}):
        create_issue_func = github_mcp.tools["github_create_issue"].fn
        res = create_issue_func("owner", "repo", "Bug Title", "Body text")
        assert "MOCK" in res

    # 3. Postgres Mock Execution
    with patch.dict(os.environ, {"POSTGRES_MOCK": "true"}):
        query_func = postgres_mcp.tools["postgres_query"].fn
        res = query_func("SELECT 1;")
        assert "Columns: 1" in res

    # 4. Browser Mock Execution
    with patch.dict(os.environ, {"BROWSER_MOCK": "true"}):
        search_func = browser_mcp.tools["browser_search"].fn
        res = search_func("test query")
        assert "MOCK" in res
