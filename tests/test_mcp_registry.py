from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import Tool

from nakama_kun.config.mcp import MCPSettings
from nakama_kun.mcp.abstractions import MCPServerStatus
from nakama_kun.mcp.client import MCPClient
from nakama_kun.mcp.manager import MCPManager
from nakama_kun.mcp.registry import MCPRegistry
from nakama_kun.tools.registry import ToolRegistry


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    # Reset registry instance before each test
    MCPRegistry._instance = None


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


@pytest.mark.anyio
async def test_mcp_tools_registered_once(temp_workspace: Path) -> None:
    """Verify that calling connect_all multiple times does not duplicate tools or change registry size."""
    # Write mock configurations
    mcp_config = temp_workspace / "mcp_config.json"
    mcp_config.write_text(
        json.dumps({
            "mcpServers": {
                "test-server": {
                    "command": "node",
                    "args": ["index.js"]
                }
            }
        }),
        encoding="utf-8"
    )

    manager = MCPManager(workspace_root=str(temp_workspace))
    tool_registry = ToolRegistry()

    # Mock MCPClient
    mock_initialize_result = MagicMock()
    mock_initialize_result.capabilities = MagicMock()
    mock_initialize_result.capabilities.model_dump.return_value = {}

    mock_client = MagicMock(spec=MCPClient)
    mock_client.name = "test-server"
    mock_client.connect = AsyncMock()
    mock_client.disconnect = AsyncMock()
    mock_client.session = MagicMock()
    mock_client.session.initialize_result = mock_initialize_result

    # Mock two tools
    tool1 = Tool(name="tool_one", description="Tool 1", inputSchema={})
    tool2 = Tool(name="tool_two", description="Tool 2", inputSchema={})
    mock_client.list_tools = AsyncMock(return_value=[tool1, tool2])

    with patch("nakama_kun.mcp.manager.MCPClient", return_value=mock_client):
        # First connect
        await manager.connect_all()

    # Get discovered tools and register in ToolRegistry (matching AgentMode/app.py logic)
    mcp_tools_1 = await manager.get_tools()
    assert len(mcp_tools_1) == 2
    for t in mcp_tools_1:
        tool_registry.register(t)

    initial_size = len(tool_registry)
    assert initial_size == 2

    # Second connect (repeated connect_all)
    with patch("nakama_kun.mcp.manager.MCPClient", return_value=mock_client):
        await manager.connect_all()

    # Retrieve and register tools again
    mcp_tools_2 = await manager.get_tools()
    for t in mcp_tools_2:
        tool_registry.register(t)

    # Size must remain stable and not double
    assert len(tool_registry) == initial_size
    assert len(tool_registry.names()) == 2
    assert len(tool_registry.all_schemas()) == 2


@pytest.mark.anyio
async def test_health_check_does_not_register_tools(temp_workspace: Path) -> None:
    """Verify that health_check() does not register/sync new tools or mutate registry tools."""
    # Write mock configurations
    mcp_config = temp_workspace / "mcp_config.json"
    mcp_config.write_text(
        json.dumps({
            "mcpServers": {
                "test-server": {
                    "command": "node",
                    "args": ["index.js"]
                }
            }
        }),
        encoding="utf-8"
    )

    manager = MCPManager(workspace_root=str(temp_workspace))

    mock_initialize_result = MagicMock()
    mock_initialize_result.capabilities = MagicMock()
    mock_initialize_result.capabilities.model_dump.return_value = {}

    mock_client = MagicMock(spec=MCPClient)
    mock_client.name = "test-server"
    mock_client.connect = AsyncMock()
    mock_client.disconnect = AsyncMock()
    mock_client.session = MagicMock()
    mock_client.session.initialize_result = mock_initialize_result

    # Initially returning tool1
    tool1 = Tool(name="tool_one", description="Tool 1", inputSchema={})
    mock_client.list_tools = AsyncMock(return_value=[tool1])

    with patch("nakama_kun.mcp.manager.MCPClient", return_value=mock_client):
        await manager.connect_all()

    # Get tools
    mcp_tools = await manager.get_tools()
    assert len(mcp_tools) == 1
    assert mcp_tools[0].name == "tool_one"

    # Now simulate a health check where list_tools returns a DIFFERENT tool (e.g. tool2)
    # Since health_check is read-only, it should NOT sync this new tool or mutate tools in registry.
    tool2 = Tool(name="tool_two", description="Tool 2", inputSchema={})
    mock_client.list_tools = AsyncMock(return_value=[tool2])

    await manager.health_check()

    # Tools in registry must remain exactly as they were (still tool1, not mutated)
    mcp_tools_after_hc = await manager.get_tools()
    assert len(mcp_tools_after_hc) == 1
    assert mcp_tools_after_hc[0].name == "tool_one"


@pytest.mark.anyio
async def test_tool_conflict_namespaced_once(temp_workspace: Path) -> None:
    """Verify that a tool name conflict between native and MCP tools results in namespaced naming exactly once each."""
    from nakama_kun.tools.interfaces import BaseTool

    # Write mock configurations
    mcp_config = temp_workspace / "mcp_config.json"
    mcp_config.write_text(
        json.dumps({
            "mcpServers": {
                "filesystem": {
                    "command": "node",
                    "args": ["index.js"]
                }
            }
        }),
        encoding="utf-8"
    )

    manager = MCPManager(workspace_root=str(temp_workspace))
    tool_registry = ToolRegistry()

    # Register native read_file tool
    class DummyTool(BaseTool):
        def __init__(self, name: str):
            self._name = name
        @property
        def name(self) -> str:
            return self._name
        @property
        def description(self) -> str:
            return "Native tool"
        @property
        def parameters(self) -> dict:
            return {}
        async def execute(self, **kwargs):
            return None

    tool_registry.register(DummyTool("read_file"))

    # Mock MCPClient for "filesystem"
    mock_initialize_result = MagicMock()
    mock_initialize_result.capabilities = MagicMock()
    mock_initialize_result.capabilities.model_dump.return_value = {}

    mock_client = MagicMock(spec=MCPClient)
    mock_client.name = "filesystem"
    mock_client.connect = AsyncMock()
    mock_client.disconnect = AsyncMock()
    mock_client.session = MagicMock()
    mock_client.session.initialize_result = mock_initialize_result

    # Mock MCP tool read_file
    mcp_tool_raw = Tool(name="read_file", description="MCP read file", inputSchema={})
    mock_client.list_tools = AsyncMock(return_value=[mcp_tool_raw])

    with patch("nakama_kun.mcp.manager.MCPClient", return_value=mock_client):
        await manager.connect_all()

    # Register in ToolRegistry
    mcp_tools = await manager.get_tools()
    for t in mcp_tools:
        tool_registry.register(t)

    # Names should contain "read_file" and "mcp_filesystem_read_file"
    all_names = tool_registry.names()
    assert "read_file" in all_names
    assert "mcp_filesystem_read_file" in all_names

    # Check exactly once occurrence of each name
    assert all_names.count("read_file") == 1
    assert all_names.count("mcp_filesystem_read_file") == 1

    # Total length should be 2
    assert len(tool_registry) == 2


@pytest.mark.anyio
async def test_reconnect_behavior(temp_workspace: Path) -> None:
    """Verify that connect -> disconnect -> reconnect sequence behaves correctly and doesn't duplicate tools."""
    mcp_config = temp_workspace / "mcp_config.json"
    mcp_config.write_text(
        json.dumps({
            "mcpServers": {
                "reconnect-server": {
                    "command": "node",
                    "args": ["index.js"]
                }
            }
        }),
        encoding="utf-8"
    )

    manager = MCPManager(workspace_root=str(temp_workspace))
    tool_registry = ToolRegistry()

    # Mock MCPClient
    mock_initialize_result = MagicMock()
    mock_initialize_result.capabilities = MagicMock()
    mock_initialize_result.capabilities.model_dump.return_value = {}

    mock_client = MagicMock(spec=MCPClient)
    mock_client.name = "reconnect-server"
    mock_client.connect = AsyncMock()
    mock_client.disconnect = AsyncMock()
    mock_client.session = MagicMock()
    mock_client.session.initialize_result = mock_initialize_result

    # Mock tools
    tool = Tool(name="reconnect_tool", description="Tool", inputSchema={})
    mock_client.list_tools = AsyncMock(return_value=[tool])

    # 1. Connect
    with patch("nakama_kun.mcp.manager.MCPClient", return_value=mock_client):
        await manager.connect_all()

    mcp_tools = await manager.get_tools()
    for t in mcp_tools:
        tool_registry.register(t)

    assert len(tool_registry) == 1
    assert "reconnect_tool" in tool_registry.names()

    # 2. Disconnect
    await manager.disconnect_all()
    # verify tools removed from server tools
    server = manager.registry.get_server("reconnect-server")
    assert server is not None
    assert len(server.tools) == 0

    # 3. Reconnect
    with patch("nakama_kun.mcp.manager.MCPClient", return_value=mock_client):
        await manager.connect_all()

    mcp_tools_2 = await manager.get_tools()
    for t in mcp_tools_2:
        tool_registry.register(t)

    # Size should still be 1 (no duplicates)
    assert len(tool_registry) == 1
    assert tool_registry.names() == ["reconnect_tool"]


@pytest.mark.anyio
async def test_duplicate_prevention_metrics(temp_workspace: Path) -> None:
    """Verify that registration_attempts, successful_registrations, and skipped_duplicates metrics track correctly."""
    mcp_config = temp_workspace / "mcp_config.json"
    mcp_config.write_text(
        json.dumps({
            "mcpServers": {
                "metric-server": {
                    "command": "node",
                    "args": ["index.js"]
                }
            }
        }),
        encoding="utf-8"
    )

    manager = MCPManager(workspace_root=str(temp_workspace))

    mock_initialize_result = MagicMock()
    mock_initialize_result.capabilities = MagicMock()
    mock_initialize_result.capabilities.model_dump.return_value = {}

    mock_client = MagicMock(spec=MCPClient)
    mock_client.name = "metric-server"
    mock_client.connect = AsyncMock()
    mock_client.disconnect = AsyncMock()
    mock_client.session = MagicMock()
    mock_client.session.initialize_result = mock_initialize_result

    # Returns exactly 1 tool
    tool1 = Tool(name="tool_one", description="Tool 1", inputSchema={})
    mock_client.list_tools = AsyncMock(return_value=[tool1])

    with patch("nakama_kun.mcp.manager.MCPClient", return_value=mock_client):
        await manager.connect_all()

    # Metrics on manager:
    # 1 attempt: 1 success ("tool_one"), 0 skipped duplicates
    assert manager.registration_attempts == 1
    assert manager.successful_registrations == 1
    assert manager.skipped_duplicates == 0

    # Now call connect_all again, which skips discovery entirely because it is already loaded
    with patch("nakama_kun.mcp.manager.MCPClient", return_value=mock_client):
        await manager.connect_all()

    # The skip of the server's tools (1 tool loaded) adds:
    # attempts += 1, skipped += 1
    assert manager.registration_attempts == 2
    assert manager.skipped_duplicates == 1
    assert manager.successful_registrations == 1
