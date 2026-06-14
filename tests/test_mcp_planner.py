from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nakama_kun.agents.planner import PlannerAgent
from nakama_kun.mcp.abstractions import MCPServer, MCPServerStatus
from nakama_kun.mcp.client import MCPClient
from nakama_kun.mcp.registry import MCPRegistry
from nakama_kun.mcp.tool import MCPTool
from nakama_kun.tools import (
    ToolRegistry,
    build_default_registry,
    ToolResult,
)
from nakama_kun.tools.selection import ToolSelectionLayer
from nakama_kun.mcp.safety import MCPSafetyControls
from nakama_kun.mcp.telemetry import MCPTelemetry


@pytest.fixture(autouse=True)
def clean_globals() -> None:
    # Reset registry, safety controls, and telemetry before/after each test
    MCPRegistry._instance = None
    MCPSafetyControls.get_instance().reset()
    MCPTelemetry.get_instance().reset()


@pytest.fixture
def populated_tool_registry() -> ToolRegistry:
    # Build default registry
    registry = build_default_registry()

    # Register an active MCP server and tools in MCPRegistry
    mcp_reg = MCPRegistry.get_instance()
    mock_client = MagicMock(spec=MCPClient)
    mock_client.name = "github"
    mock_client.call_tool = AsyncMock()

    mcp_tool = MCPTool(
        client=mock_client,
        original_name="create_issue",
        name="github_create_issue",
        description="Creates a Github issue.\nPermissions: github_write\nCategories: github, vcs\nUsage: Create issue.",
        parameters={"type": "object", "properties": {}},
    )

    server = MCPServer(
        name="github",
        status=MCPServerStatus.CONNECTED,
        capabilities={},
        tools=[mcp_tool],
    )
    mcp_reg.register_server(server)
    return registry


@pytest.mark.anyio
async def test_planner_tool_capability_summary_injection(populated_tool_registry: ToolRegistry) -> None:
    # Mock ChatService provider
    mock_chat = MagicMock()
    mock_response = MagicMock()
    mock_response.content = '{"goal_summary": "test goal", "assumptions": [], "ordered_steps": [], "required_artifacts": [], "risks": [], "validation_checklist": [], "targets": []}'
    mock_chat.provider.generate = AsyncMock(return_value=mock_response)

    agent = PlannerAgent(mock_chat, tool_registry=populated_tool_registry)

    # Trigger planning task
    await agent.run({"goal": "Test goal with github"})

    # Verify that the provider was called with the capability summary
    called_messages = mock_chat.provider.generate.call_args[0][0]
    system_message = next(m for m in called_messages if m.role == "system")

    # Assert local and MCP tools are in the capability summary injected in system prompt
    assert "### Available Tools and Capability Summary" in system_message.content
    assert "github_create_issue" in system_message.content
    assert "Server: github" in system_message.content
    assert "read_file" in system_message.content


def test_tool_selection_layer_redundancy_and_local_preference() -> None:
    # 1. Redundant Calls Blocked
    history = [
        {"tool": "read_file", "arguments": {"path": "test.txt"}, "success": True}
    ]
    selection = ToolSelectionLayer(history)

    # Repeat read_file call
    name, args, block_reason = selection.filter_and_optimize("read_file", {"path": "test.txt"})
    assert block_reason is not None
    assert "Redundant" in block_reason

    # 2. Local Preference Redirects
    selection_empty = ToolSelectionLayer([])
    name, args, block_reason = selection_empty.filter_and_optimize("mcp_filesystem_read_file", {"path": "test.txt"})
    assert block_reason is None
    assert name == "read_file"  # Redirected to local tool!


@pytest.mark.anyio
async def test_safety_controls_restrictions() -> None:
    mock_client = MagicMock()
    mock_client.name = "github"
    mock_client.call_tool = AsyncMock()

    mcp_tool = MCPTool(
        client=mock_client,
        original_name="create_issue",
        name="github_create_issue",
        description="Creates a Github issue.",
        parameters={},
    )

    safety = MCPSafetyControls.get_instance()

    # 1. Server Allowlist violation
    safety.set_allowed_servers(["postgres"])  # github not in allowlist
    res = await mcp_tool.execute()
    assert res.success is False
    assert "SAFETY_VIOLATION" in res.error
    assert "Server" in res.error

    # 2. Read-Only Mode blocks mutating action
    safety.reset()
    safety.set_read_only(True)
    res = await mcp_tool.execute()  # github_create_issue contains "create" and is considered mutating
    assert res.success is False
    assert "SAFETY_VIOLATION" in res.error
    assert "Read-Only Mode" in res.error


@pytest.mark.anyio
async def test_telemetry_tracking() -> None:
    mock_client = MagicMock()
    mock_client.name = "github"
    
    mock_result = MagicMock()
    mock_result.is_error = False
    mock_result.isError = False
    mock_result.content = []
    mock_client.call_tool = AsyncMock(return_value=mock_result)

    mcp_tool = MCPTool(
        client=mock_client,
        original_name="get_issue",
        name="github_get_issue",  # Read-only tool
        description="Get issue.",
        parameters={},
    )

    telemetry = MCPTelemetry.get_instance()
    assert len(telemetry.metrics) == 0

    # Execute successfully
    res = await mcp_tool.execute()
    assert len(telemetry.metrics) == 1
    metric = telemetry.metrics[0]
    assert metric.server == "github"
    assert metric.tool == "github_get_issue"
    assert metric.success is True
    assert metric.latency_ms > 0

    stats = telemetry.get_stats()
    assert stats["total_calls"] == 1
    assert stats["success_rate"] == 1.0
    assert "github" in stats["servers"]
