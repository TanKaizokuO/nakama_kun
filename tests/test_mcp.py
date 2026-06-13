from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import CallToolResult, TextContent, Tool

from nakama_kun.config.mcp import MCPServerConfig, MCPSettings
from nakama_kun.mcp.client import MCPClient
from nakama_kun.mcp.manager import MCPManager
from nakama_kun.mcp.tool import MCPTool, is_mutating_tool
from nakama_kun.safety.models import AutoApprovalProvider


def test_is_mutating_tool() -> None:
    """Verify mutating tool name detection patterns."""
    assert is_mutating_tool("write_file") is True
    assert is_mutating_tool("create_issue") is True
    assert is_mutating_tool("delete_item") is True
    assert is_mutating_tool("get_records") is False
    assert is_mutating_tool("list_directory") is False


def test_mcp_settings_load_servers_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loading server configurations from MCP_SERVERS_JSON env var."""
    config_dict = {
        "mcpServers": {
            "test-server": {
                "command": "python",
                "args": ["-m", "test"],
                "env": {"KEY": "VALUE"}
            }
        }
    }
    monkeypatch.setenv("MCP_SERVERS_JSON", json.dumps(config_dict))

    settings = MCPSettings()
    servers = settings.load_servers()

    assert "test-server" in servers
    assert servers["test-server"].command == "python"
    assert servers["test-server"].args == ["-m", "test"]
    assert servers["test-server"].env == {"KEY": "VALUE"}


def test_mcp_settings_load_servers_file(tmp_path: Path) -> None:
    """Test loading server configurations from mcp_config.json file."""
    config_dict = {
        "mcp_servers": {
            "file-server": {
                "command": "node",
                "args": ["index.js"]
            }
        }
    }
    config_file = tmp_path / "mcp_config.json"
    config_file.write_text(json.dumps(config_dict), encoding="utf-8")

    settings = MCPSettings(mcp_config_path=str(config_file))
    servers = settings.load_servers(workspace_root=str(tmp_path))

    assert "file-server" in servers
    assert servers["file-server"].command == "node"
    assert servers["file-server"].args == ["index.js"]


@pytest.mark.anyio
@patch("nakama_kun.mcp.client.stdio_client")
@patch("nakama_kun.mcp.client.ClientSession")
async def test_mcp_client_connect_success(mock_session_cls: MagicMock, mock_stdio_client: MagicMock) -> None:
    """Test successful MCPClient connection and initialization."""
    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.initialize = AsyncMock()
    mock_session_cls.return_value = mock_session

    mock_stdio_context = AsyncMock()
    mock_stdio_context.__aenter__.return_value = (MagicMock(), MagicMock())
    mock_stdio_client.return_value = mock_stdio_context

    client = MCPClient("test", "command", ["arg1"])
    await client.connect()

    assert client.session is not None
    mock_session.initialize.assert_awaited_once()


@pytest.mark.anyio
@patch("nakama_kun.mcp.client.stdio_client")
async def test_mcp_client_connect_failure(mock_stdio_client: MagicMock) -> None:
    """Test clean disconnection handling on MCPClient connection failure."""
    mock_stdio_client.side_effect = Exception("Connection error")

    client = MCPClient("test", "command", ["arg1"])
    with pytest.raises(Exception, match="Connection error"):
        await client.connect()

    assert client.session is None


@pytest.mark.anyio
@patch("nakama_kun.mcp.client.stdio_client")
@patch("nakama_kun.mcp.client.ClientSession")
async def test_mcp_manager_connect_all_non_blocking(mock_session_cls: MagicMock, mock_stdio_client: MagicMock) -> None:
    """Test that failure in one server connection does not block other servers in MCPManager."""
    with patch.object(MCPSettings, "load_servers") as mock_load:
        mock_load.return_value = {
            "server1": MCPServerConfig(command="python", args=[]),
            "server2": MCPServerConfig(command="node", args=[]),
        }

        with patch("nakama_kun.mcp.manager.MCPClient") as MockClient:
            inst1 = MagicMock()
            inst1.connect = AsyncMock(side_effect=Exception("Failed to connect"))
            inst2 = MagicMock()
            inst2.connect = AsyncMock()

            MockClient.side_effect = [inst1, inst2]

            manager = MCPManager()
            await manager.connect_all()

            inst1.connect.assert_called_once()
            inst2.connect.assert_called_once()
            assert "server2" in manager.clients
            assert "server1" not in manager.clients


@pytest.mark.anyio
async def test_mcp_manager_tool_naming_conflict() -> None:
    """Test resolving conflicts between built-in tools and MCP server tools by prefixing."""
    manager = MCPManager()

    client1 = MagicMock(spec=MCPClient)
    client1.name = "git"
    tool1 = Tool(name="read_file", description="Read git file", inputSchema={})
    client1.list_tools = AsyncMock(return_value=[tool1])

    client2 = MagicMock(spec=MCPClient)
    client2.name = "postgres"
    tool2 = Tool(name="query", description="Query DB", inputSchema={})
    client2.list_tools = AsyncMock(return_value=[tool2])

    manager.clients = {"git": client1, "postgres": client2}

    mcp_tools = await manager.get_tools()

    names = {t.name for t in mcp_tools}
    # read_file is a built-in, so it is renamed to mcp_git_read_file
    assert "mcp_git_read_file" in names
    assert "query" in names


@pytest.mark.anyio
async def test_mcp_tool_execute_read_only() -> None:
    """Test executing a read-only tool directly without user confirmation."""
    client = MagicMock(spec=MCPClient)
    client.name = "test-server"

    mock_result = CallToolResult(content=[TextContent(type="text", text="output_data")], isError=False)
    client.call_tool = AsyncMock(return_value=mock_result)

    tool = MCPTool(
        client=client,
        original_name="get_data",
        name="get_data",
        description="Read only tool",
        parameters={},
        approval_provider=None
    )

    result = await tool.execute()
    assert result.success is True
    assert result.output == "output_data"
    client.call_tool.assert_awaited_once_with("get_data", {})


@pytest.mark.anyio
async def test_mcp_tool_execute_mutating_approved() -> None:
    """Test executing a mutating tool that is approved by AutoApprovalProvider."""
    client = MagicMock(spec=MCPClient)
    client.name = "test-server"

    mock_result = CallToolResult(content=[TextContent(type="text", text="created")], isError=False)
    client.call_tool = AsyncMock(return_value=mock_result)

    provider = AutoApprovalProvider(approve=True)

    tool = MCPTool(
        client=client,
        original_name="create_file",
        name="create_file",
        description="Mutating tool",
        parameters={},
        approval_provider=provider
    )

    result = await tool.execute(path="test.txt")
    assert result.success is True
    assert result.output == "created"
    client.call_tool.assert_awaited_once_with("create_file", {"path": "test.txt"})


@pytest.mark.anyio
async def test_mcp_tool_execute_mutating_rejected() -> None:
    """Test executing a mutating tool that is rejected by AutoApprovalProvider."""
    client = MagicMock(spec=MCPClient)
    client.name = "test-server"

    provider = AutoApprovalProvider(approve=False)

    tool = MCPTool(
        client=client,
        original_name="create_file",
        name="create_file",
        description="Mutating tool",
        parameters={},
        approval_provider=provider
    )

    result = await tool.execute(path="test.txt")
    assert result.success is False
    assert "rejected" in result.error
    client.call_tool.assert_not_called()
