from __future__ import annotations

import json
from typing import Any

from loguru import logger

from nakama_kun.mcp.client import MCPClient
from nakama_kun.tools.interfaces import BaseTool, ToolResult


def is_mutating_tool(name: str) -> bool:
    """Helper to detect if a tool is a modify/write tool based on common mutating name patterns."""
    patterns = [
        "create",
        "write",
        "update",
        "delete",
        "post",
        "execute",
        "run",
        "remove",
        "add",
        "modify",
        "send",
        "publish",
        "save",
        "patch",
        "destroy",
    ]
    name_lower = name.lower()
    return any(p in name_lower for p in patterns)


class MCPTool(BaseTool):
    """Bridge tool that inherits from BaseTool and routes calls to an external MCP server."""

    def __init__(
        self,
        client: MCPClient,
        original_name: str,
        name: str,
        description: str,
        parameters: dict[str, Any],
        approval_provider: Any | None = None,
    ) -> None:
        self.client = client
        self.original_name = original_name
        self.name = name
        self.description = description
        self.parameters = parameters
        self.approval_provider = approval_provider

    @property
    def server_name(self) -> str:
        """The name of the parent MCP server."""
        return self.client.name

    @property
    def schema(self) -> dict[str, Any]:
        """The tool's parameters schema."""
        return self.parameters

    @property
    def permissions(self) -> list[str]:  # type: ignore[override]
        return self._parse_metadata("Permissions") or [f"{self.server_name}_access"]

    @property
    def categories(self) -> list[str]:  # type: ignore[override]
        return self._parse_metadata("Categories") or [self.server_name]

    @property
    def usage_description(self) -> str:  # type: ignore[override]
        return self._parse_metadata_str("Usage") or self.description

    def _parse_metadata(self, key: str) -> list[str] | None:
        val = self._parse_metadata_str(key)
        if val:
            val = val.strip("[]'\"")
            return [p.strip().strip("'\"") for p in val.split(",") if p.strip()]
        return None

    def _parse_metadata_str(self, key: str) -> str | None:
        import re
        pattern = rf"(?i)\b{key}\s*:\s*(.+)"
        match = re.search(pattern, self.description)
        if match:
            return match.group(1).split("\n")[0].strip()
        return None

    async def execute(self, **kwargs: Any) -> ToolResult:
        # 1. Enforce safety gating for mutating actions
        if is_mutating_tool(self.original_name) or is_mutating_tool(self.name):
            approved = await self._request_approval(kwargs)
            if not approved:
                return ToolResult(
                    success=False,
                    error=f"Execution of mutating external tool '{self.name}' was rejected by the user.",
                )

        # 2. Call tool via client session
        try:
            result = await self.client.call_tool(self.original_name, kwargs)
            output = self._format_content(result.content)
            is_error = getattr(result, "is_error", getattr(result, "isError", False))

            if is_error:
                return ToolResult(success=False, error=output)
            return ToolResult(success=True, output=output)
        except Exception as e:
            logger.error(f"Error during execution of MCP tool '{self.name}': {e}")
            return ToolResult(success=False, error=str(e))

    async def _request_approval(self, arguments: dict[str, Any]) -> bool:
        """Asks for confirmation to run a mutating/modifying external tool."""
        if self.approval_provider is None:
            # Non-interactive or testing fallback
            try:
                import questionary
                approved = await questionary.confirm(
                    f"⚠️ Run external tool '{self.name}'?",
                    default=False
                ).ask_async()
                return bool(approved)
            except Exception:
                return False

        from nakama_kun.safety.models import AutoApprovalProvider

        if isinstance(self.approval_provider, AutoApprovalProvider):
            return self.approval_provider.approve

        # Standard Terminal prompt
        import questionary
        from rich.console import Console
        from rich.panel import Panel
        from rich.syntax import Syntax

        console = getattr(self.approval_provider, "console", None) or Console()
        console.print()

        title_str = f"[bold yellow]⚠️ Proposed External Action: MCP Tool '{self.name}'[/bold yellow]"
        args_json = json.dumps(arguments, indent=2, ensure_ascii=False)
        args_syntax = Syntax(args_json, "json", theme="monokai", word_wrap=True)

        console.print(
            Panel(
                args_syntax,
                title=title_str,
                subtitle=f"Server: {self.client.name}",
                border_style="yellow",
                padding=(1, 2),
            )
        )

        try:
            approved = await questionary.confirm(
                f"Do you approve executing MCP tool '{self.name}'?", default=False
            ).ask_async()
        except (KeyboardInterrupt, EOFError):
            approved = False

        if not approved:
            console.print(f"[bold red]✗ External action '{self.name}' rejected by user.[/bold red]\n")
        else:
            console.print(f"[bold green]✓ External action '{self.name}' approved and executing.[/bold green]\n")

        return bool(approved)

    def _format_content(self, content_blocks: list[Any] | None) -> str:
        """Helper to format various MCP content blocks into a clean output string."""
        if not content_blocks:
            return ""

        parts = []
        for block in content_blocks:
            if hasattr(block, "text"):
                parts.append(block.text)
            elif isinstance(block, dict) and "text" in block:
                parts.append(block["text"])
            elif hasattr(block, "type"):
                parts.append(f"[{block.type.upper()} CONTENT]")
            elif isinstance(block, dict) and "type" in block:
                parts.append(f"[{block['type'].upper()} CONTENT]")
            else:
                parts.append(str(block))

        return "\n".join(parts)
