from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from mcp.types import CallToolResult, TextContent
from nakama_kun.mcp.abstractions import MCPServer, MCPServerStatus
from nakama_kun.mcp.client import MCPClient
from nakama_kun.mcp.registry import MCPRegistry
from nakama_kun.mcp.tool import MCPTool
from nakama_kun.tools import (
    ToolRegistry,
    ToolRouter,
    ToolDiscoveryService,
    BaseTool,
    ToolResult,
    build_default_registry,
)
from nakama_kun.tools.adapters import MCPToolAdapter


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    # Reset MCPRegistry singleton instance
    MCPRegistry._instance = None


@pytest.fixture
def populated_registries() -> tuple[ToolRegistry, MCPRegistry]:
    # 1. Create default local tool registry
    local_reg = build_default_registry()

    # 2. Get and populate MCPRegistry
    mcp_reg = MCPRegistry.get_instance()

    mock_client = MagicMock(spec=MCPClient)
    mock_client.name = "github"

    # Mock tool execution return
    mock_result = CallToolResult(content=[TextContent(type="text", text="issue-123")], isError=False)
    mock_client.call_tool = AsyncMock(return_value=mock_result)

    from nakama_kun.safety.models import AutoApprovalProvider

    mcp_tool_raw = MCPTool(
        client=mock_client,
        original_name="create_issue",
        name="github_create_issue",
        description="Creates a Github issue",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["title"],
        },
        approval_provider=AutoApprovalProvider(approve=True),
    )

    server = MCPServer(
        name="github",
        status=MCPServerStatus.CONNECTED,
        capabilities={},
        tools=[mcp_tool_raw],
    )
    mcp_reg.register_server(server)

    return local_reg, mcp_reg


@pytest.mark.anyio
async def test_local_tool_execution(populated_registries: tuple[ToolRegistry, MCPRegistry]) -> None:
    local_reg, _ = populated_registries
    router = ToolRouter(local_reg)

    # list_files is a standard built-in local tool
    # Wait, let's write a file first or verify list_files execution
    res = await router.dispatch("list_files", {})
    assert res.success is True
    assert res.output is not None


@pytest.mark.anyio
async def test_mcp_tool_execution(populated_registries: tuple[ToolRegistry, MCPRegistry]) -> None:
    local_reg, mcp_reg = populated_registries
    router = ToolRouter(local_reg)

    # Verify that github_create_issue (external MCP tool) is resolvable
    assert "github_create_issue" in local_reg.names()

    # Dispatch external tool call
    res = await router.dispatch(
        "github_create_issue",
        {"title": "Bug: Something is broken", "body": "Please fix it"},
    )

    assert res.success is True
    assert res.output == "issue-123"

    # Verify call tool was routed to mcp client
    mock_client = mcp_reg.get_server("github").tools[0].client  # type: ignore[union-attr]
    mock_client.call_tool.assert_awaited_once_with(
        "create_issue",
        {"title": "Bug: Something is broken", "body": "Please fix it"},
    )


def test_mixed_tool_inventories(populated_registries: tuple[ToolRegistry, MCPRegistry]) -> None:
    local_reg, _ = populated_registries

    # Must contain both local tools (e.g. read_file) and MCP tools (e.g. github_create_issue)
    names = local_reg.names()
    assert "read_file" in names
    assert "github_create_issue" in names

    schemas = local_reg.all_schemas()
    schema_names = [s["function"]["name"] for s in schemas]
    assert "read_file" in schema_names
    assert "github_create_issue" in schema_names

    # Check length
    assert len(local_reg) == len(names)


def test_schema_compatibility(populated_registries: tuple[ToolRegistry, MCPRegistry]) -> None:
    local_reg, _ = populated_registries

    # Retrieve mcp tool adapter schema
    tool = local_reg.get("github_create_issue")
    assert isinstance(tool, MCPToolAdapter)

    schema = tool.to_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "github_create_issue"
    assert schema["function"]["description"] == "Creates a Github issue"
    assert schema["function"]["parameters"] == {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["title"],
    }


def test_tool_discovery_service(populated_registries: tuple[ToolRegistry, MCPRegistry]) -> None:
    local_reg, _ = populated_registries
    discovery = ToolDiscoveryService(local_reg)

    # 1. list_available_tools
    available = discovery.list_available_tools()
    names = [t.name for t in available]
    assert "read_file" in names
    assert "github_create_issue" in names

    # 2. find_tool
    tool = discovery.find_tool("github_create_issue")
    assert tool is not None
    assert tool.name == "github_create_issue"

    missing = discovery.find_tool("nonexistent_tool")
    assert missing is None

    # 3. get_tool_schema
    schema = discovery.get_tool_schema("github_create_issue")
    assert schema is not None
    assert schema == {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["title"],
    }

    missing_schema = discovery.get_tool_schema("nonexistent_tool")
    assert missing_schema is None
