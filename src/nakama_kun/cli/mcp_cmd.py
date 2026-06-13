from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from nakama_kun.mcp.manager import MCPManager

mcp_app = typer.Typer(
    name="mcp",
    help="Manage and inspect external Model Context Protocol (MCP) servers.",
    no_args_is_help=True,
)
console = Console()


async def _list_servers_async() -> None:
    manager = MCPManager()
    console.print("[bold yellow]Connecting to configured MCP servers...[/bold yellow]")
    await manager.connect_all()

    table = Table(title="Configured MCP Servers")
    table.add_column("Server Name", style="cyan")
    table.add_column("Status", style="bold green")
    table.add_column("Command", style="dim")
    table.add_column("Arguments", style="dim")

    configs = manager.settings.load_servers(manager.workspace_root)
    if not configs:
        console.print("[yellow]No MCP servers configured in mcp_config.json or MCP_SERVERS_JSON.[/yellow]")
        await manager.disconnect_all()
        return

    for name, cfg in configs.items():
        connected = name in manager.clients
        status = "Connected" if connected else "Failed"
        status_style = "bold green" if connected else "bold red"
        table.add_row(
            name,
            f"[{status_style}]{status}[/{status_style}]",
            cfg.command,
            " ".join(cfg.args),
        )

    console.print(table)
    await manager.disconnect_all()


async def _list_tools_async() -> None:
    manager = MCPManager()
    console.print("[bold yellow]Connecting to configured MCP servers to list tools...[/bold yellow]")
    await manager.connect_all()

    mcp_tools = await manager.get_tools()
    if not mcp_tools:
        console.print("[yellow]No tools discovered on any active MCP server.[/yellow]")
    else:
        for tool in mcp_tools:
            console.print()
            title = f"[bold cyan]Tool: {tool.name}[/bold cyan] (via {tool.client.name})"
            details = (
                f"[bold]Description:[/bold] {tool.description}\n"
                f"[bold]Parameters Schema:[/bold] {tool.parameters}"
            )
            console.print(
                Panel(
                    details,
                    title=title,
                    border_style="cyan",
                )
            )

    await manager.disconnect_all()


@mcp_app.command("list-servers")
def list_servers_command() -> None:
    """List all configured MCP servers and check connection status."""
    try:
        asyncio.run(_list_servers_async())
    except Exception as e:
        console.print(f"[bold red]Error listing MCP servers: {e}[/bold red]")
        raise typer.Exit(1) from e


@mcp_app.command("list-tools")
def list_tools_command() -> None:
    """List all tools exposed by connected MCP servers."""
    try:
        asyncio.run(_list_tools_async())
    except Exception as e:
        console.print(f"[bold red]Error listing MCP tools: {e}[/bold red]")
        raise typer.Exit(1) from e
