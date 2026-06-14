import pytest
from nakama_kun.mcp.registry import MCPRegistry


@pytest.fixture(autouse=True)
def reset_mcp_registry() -> None:
    """Reset the MCPRegistry singleton instance to ensure clean test isolation."""
    MCPRegistry._instance = None
