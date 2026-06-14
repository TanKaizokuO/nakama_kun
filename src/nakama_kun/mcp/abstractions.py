from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from nakama_kun.mcp.tool import MCPTool


class MCPServerStatus:
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    ERROR = "ERROR"
    STARTING = "STARTING"


@dataclass
class MCPServer:
    name: str
    status: str
    capabilities: dict[str, Any] = field(default_factory=dict)
    tools: list[MCPTool] = field(default_factory=list)
