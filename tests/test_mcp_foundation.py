from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import Tool

from nakama_kun.mcp.abstractions import MCPServer, MCPServerStatus
from nakama_kun.mcp.client import MCPClient
from nakama_kun.mcp.manager import MCPManager
from nakama_kun.mcp.registry import MCPRegistry
from nakama_kun.mcp.tool import MCPTool


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    # Reset registry instance before each test
    MCPRegistry._instance = None


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def test_server_registration() -> None:
    registry = MCPRegistry.get_instance()
    
    server = MCPServer(
        name="test_server",
        status=MCPServerStatus.CONNECTED,
        capabilities={"tools": {}},
        tools=[],
    )
    
    registry.register_server(server)
    assert registry.get_server("test_server") is server
    assert len(registry.list_servers()) == 1


def test_duplicate_registration() -> None:
    registry = MCPRegistry.get_instance()
    
    server1 = MCPServer(
        name="test_server",
        status=MCPServerStatus.CONNECTED,
        capabilities={},
        tools=[],
    )
    server2 = MCPServer(
        name="test_server",
        status=MCPServerStatus.DISCONNECTED,
        capabilities={},
        tools=[],
    )
    
    registry.register_server(server1)
    with pytest.raises(ValueError, match="already registered"):
        registry.register_server(server2)


def test_registry_lookups() -> None:
    registry = MCPRegistry.get_instance()
    mock_client = MagicMock(spec=MCPClient)
    mock_client.name = "server1"

    tool1 = MCPTool(
        client=mock_client,
        original_name="tool_a",
        name="tool_a",
        description="Tool A",
        parameters={"type": "object"},
    )
    tool2 = MCPTool(
        client=mock_client,
        original_name="tool_b",
        name="mcp_server1_tool_b",
        description="Tool B",
        parameters={"type": "object"},
    )

    server = MCPServer(
        name="server1",
        status=MCPServerStatus.CONNECTED,
        capabilities={},
        tools=[tool1, tool2],
    )
    registry.register_server(server)

    assert registry.get_server("server1") is server
    assert len(registry.list_tools()) == 2
    assert registry.find_tool("tool_a") is tool1
    assert registry.find_tool("mcp_server1_tool_b") is tool2
    assert registry.find_tool("nonexistent") is None

    # Unregister
    registry.unregister_server("server1")
    assert registry.get_server("server1") is None
    assert len(registry.list_tools()) == 0


@pytest.mark.anyio
async def test_mcp_manager_lifecycle_and_discovery(temp_workspace: Path) -> None:
    # Set up config files: mcp.yaml
    mcp_yaml = temp_workspace / "mcp.yaml"
    mcp_yaml.write_text(
        "servers:\n"
        "  github:\n"
        "    enabled: true\n"
        "  postgres:\n"
        "    enabled: false\n",
        encoding="utf-8"
    )

    # mcp_config.json
    mcp_config = temp_workspace / "mcp_config.json"
    mcp_config.write_text(
        json.dumps({
            "mcpServers": {
                "github": {
                    "command": "node",
                    "args": ["github.js"]
                },
                "postgres": {
                    "command": "python",
                    "args": ["postgres.py"]
                }
            }
        }),
        encoding="utf-8"
    )

    manager = MCPManager(workspace_root=str(temp_workspace))

    # Mock MCPClient connection and list_tools
    mock_initialize_result = MagicMock()
    mock_initialize_result.capabilities = MagicMock()
    mock_initialize_result.capabilities.model_dump.return_value = {"resources": {}}

    mock_client = MagicMock(spec=MCPClient)
    mock_client.name = "github"
    mock_client.connect = AsyncMock()
    mock_client.disconnect = AsyncMock()
    mock_client.session = MagicMock()
    mock_client.session.initialize_result = mock_initialize_result

    # Mock tool returned from mcp
    mock_tool = Tool(
        name="get_issue",
        description="Get GitHub Issue",
        inputSchema={"type": "object", "properties": {}},
    )
    mock_client.list_tools = AsyncMock(return_value=[mock_tool])

    with patch("nakama_kun.mcp.manager.MCPClient", return_value=mock_client):
        await manager.connect_all()

    # Verify server status in registry
    registry = manager.registry
    server = registry.get_server("github")
    assert server is not None
    assert server.status == MCPServerStatus.CONNECTED
    assert "resources" in server.capabilities

    # Verify postgres was skipped because it's disabled in mcp.yaml
    assert registry.get_server("postgres") is None

    # Verify tool discovery
    tools = await manager.get_tools()
    assert len(tools) == 1
    assert tools[0].name == "get_issue"
    assert tools[0].server_name == "github"
    assert tools[0].schema == {"type": "object", "properties": {}}

    # Health check sync verification
    await manager.health_check()
    assert server.status == MCPServerStatus.CONNECTED


@pytest.mark.anyio
async def test_manager_disconnect_handling(temp_workspace: Path) -> None:
    # Setup standard config
    mcp_config = temp_workspace / "mcp_config.json"
    mcp_config.write_text(
        json.dumps({
            "mcpServers": {
                "github": {
                    "command": "node",
                    "args": ["github.js"]
                }
            }
        }),
        encoding="utf-8"
    )

    manager = MCPManager(workspace_root=str(temp_workspace))

    mock_client = MagicMock(spec=MCPClient)
    mock_client.name = "github"
    mock_client.connect = AsyncMock()
    mock_client.disconnect = AsyncMock()
    mock_client.session = MagicMock()
    mock_client.list_tools = AsyncMock(return_value=[])

    with patch("nakama_kun.mcp.manager.MCPClient", return_value=mock_client):
        await manager.connect_all()

    registry = manager.registry
    server = registry.get_server("github")
    assert server is not None
    assert server.status == MCPServerStatus.CONNECTED

    # Disconnect
    await manager.disconnect_all()
    assert server.status == MCPServerStatus.DISCONNECTED
    assert len(server.tools) == 0
