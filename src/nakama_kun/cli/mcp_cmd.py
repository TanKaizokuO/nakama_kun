from __future__ import annotations

import asyncio
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from nakama_kun.mcp.manager import MCPManager
from nakama_kun.mcp.abstractions import MCPServerStatus

mcp_app = typer.Typer(
    name="mcp",
    help="Manage and inspect external Model Context Protocol (MCP) servers.",
    no_args_is_help=True,
)
console = Console()


async def _status_async() -> None:
    manager = MCPManager()
    console.print("[bold yellow]Connecting to configured MCP servers...[/bold yellow]")
    await manager.connect_all()

    table = Table(title="MCP Server Status Overview")
    table.add_column("Server Name", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Capabilities", style="dim")
    table.add_column("Tools Count", style="magenta")

    servers = manager.registry.list_servers()
    if not servers:
        console.print("[yellow]No MCP servers configured or active.[/yellow]")
        await manager.disconnect_all()
        return

    for server in servers:
        status = server.status
        if status == MCPServerStatus.CONNECTED:
            status_style = "bold green"
        elif status == MCPServerStatus.STARTING:
            status_style = "bold yellow"
        elif status == MCPServerStatus.ERROR:
            status_style = "bold red"
        else:
            status_style = "bold white"

        caps_keys = list(server.capabilities.keys())
        caps_str = ", ".join(caps_keys) if caps_keys else "none"
        
        table.add_row(
            server.name,
            f"[{status_style}]{status}[/{status_style}]",
            caps_str,
            str(len(server.tools)),
        )

    console.print(table)
    await manager.disconnect_all()


async def _list_async() -> None:
    manager = MCPManager()
    console.print("[bold yellow]Connecting to configured MCP servers to list tools...[/bold yellow]")
    await manager.connect_all()

    tools = manager.registry.list_tools()
    if not tools:
        console.print("[yellow]No tools discovered on any active MCP server.[/yellow]")
    else:
        for tool in tools:
            console.print()
            title = f"[bold cyan]Tool: {tool.name}[/bold cyan] (via {tool.server_name})"
            details = (
                f"[bold]Description:[/bold] {tool.description}\n"
                f"[bold]Parameters Schema:[/bold] {tool.schema}"
            )
            console.print(
                Panel(
                    details,
                    title=title,
                    border_style="cyan",
                )
            )

    await manager.disconnect_all()


async def _inspect_async(server_name: str) -> None:
    manager = MCPManager()
    console.print(f"[bold yellow]Connecting to MCP servers to inspect '{server_name}'...[/bold yellow]")
    await manager.connect_all()

    server = manager.registry.get_server(server_name)
    if not server:
        console.print(f"[bold red]Error: MCP Server '{server_name}' is not configured or registered.[/bold red]")
        await manager.disconnect_all()
        return

    console.print()
    status_style = "bold green" if server.status == MCPServerStatus.CONNECTED else "bold red"
    title = f"[bold cyan]MCP Server Details: {server.name}[/bold cyan]"
    
    caps_str = ", ".join(server.capabilities.keys()) if server.capabilities else "none"
    
    details = (
        f"[bold]Status:[/bold] [{status_style}]{server.status}[/{status_style}]\n"
        f"[bold]Capabilities:[/bold] {caps_str}\n"
        f"[bold]Tools Count:[/bold] {len(server.tools)}"
    )
    console.print(Panel(details, title=title, border_style="cyan"))

    if server.tools:
        console.print("\n[bold]Exposed Tools:[/bold]")
        for tool in server.tools:
            tool_info = (
                f"[bold]Description:[/bold] {tool.description}\n"
                f"[bold]Schema:[/bold] {tool.schema}"
            )
            console.print(
                Panel(
                    tool_info,
                    title=f"[cyan]{tool.name}[/cyan]",
                    border_style="dim",
                )
            )
    else:
        console.print("\n[yellow]No tools exposed by this server.[/yellow]")

    await manager.disconnect_all()


@mcp_app.command("status")
def status_command() -> None:
    """Print the status of all configured MCP servers."""
    try:
        asyncio.run(_status_async())
    except Exception as e:
        console.print(f"[bold red]Error showing MCP status: {e}[/bold red]")
        raise typer.Exit(1) from e


@mcp_app.command("list")
def list_command() -> None:
    """List all tools exposed by connected MCP servers."""
    try:
        asyncio.run(_list_async())
    except Exception as e:
        console.print(f"[bold red]Error listing MCP tools: {e}[/bold red]")
        raise typer.Exit(1) from e


@mcp_app.command("inspect")
def inspect_command(
    server: str = typer.Argument(..., help="The name of the MCP server to inspect.")
) -> None:
    """Inspect connection details, capabilities, and tools of a specific MCP server."""
    try:
        asyncio.run(_inspect_async(server))
    except Exception as e:
        console.print(f"[bold red]Error inspecting MCP server '{server}': {e}[/bold red]")
        raise typer.Exit(1) from e


@mcp_app.command("test")
def test_command(
    server: str = typer.Argument(..., help="The name of the MCP server to test connection and authentication (e.g. github, postgres, browser, filesystem).")
) -> None:
    """Test connection and authentication for a specific MCP server."""
    from nakama_kun.mcp.auth import MCPAuthManager
    console.print(f"[bold yellow]Testing connection to '{server}'...[/bold yellow]")

    success, message = MCPAuthManager.validate_connection(server)
    if success:
        console.print(f"[bold green]✓ {message}[/bold green]")
    else:
        console.print(f"[bold red]✗ {message}[/bold red]")
        raise typer.Exit(1)
