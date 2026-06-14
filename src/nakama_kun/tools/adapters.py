from __future__ import annotations

from typing import Any, TYPE_CHECKING

from nakama_kun.tools.interfaces import BaseTool, ToolResult

if TYPE_CHECKING:
    from nakama_kun.mcp.tool import MCPTool


class MCPToolAdapter(BaseTool):
    """Adapts an MCPTool instance to look and behave exactly like a BaseTool/UnifiedTool."""

    def __init__(self, mcp_tool: MCPTool) -> None:
        self.mcp_tool = mcp_tool

    @property
    def name(self) -> str:  # type: ignore[override]
        return self.mcp_tool.name

    @property
    def description(self) -> str:  # type: ignore[override]
        return self.mcp_tool.description

    @property
    def parameters(self) -> dict[str, Any]:  # type: ignore[override]
        return self.mcp_tool.parameters

    @property
    def permissions(self) -> list[str]:  # type: ignore[override]
        return self._parse_metadata("Permissions") or [f"{self.mcp_tool.server_name}_access"]

    @property
    def categories(self) -> list[str]:  # type: ignore[override]
        return self._parse_metadata("Categories") or [self.mcp_tool.server_name]

    @property
    def usage_description(self) -> str:  # type: ignore[override]
        return self._parse_metadata_str("Usage") or self.description

    def _parse_metadata(self, key: str) -> list[str] | None:
        val = self._parse_metadata_str(key)
        if val:
            return [p.strip() for p in val.split(",") if p.strip()]
        return None

    def _parse_metadata_str(self, key: str) -> str | None:
        import re
        pattern = rf"(?i)\b{key}\s*:\s*(.+)"
        match = re.search(pattern, self.mcp_tool.description)
        if match:
            return match.group(1).split("\n")[0].strip()
        return None

    async def execute(self, **kwargs: Any) -> ToolResult:
        return await self.mcp_tool.execute(**kwargs)
