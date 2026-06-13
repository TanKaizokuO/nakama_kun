from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel

from nakama_kun.rag import get_indexer, get_vector_store

rag_app = typer.Typer(
    name="rag",
    help="Manage and query the workspace vector index (RAG).",
    no_args_is_help=True,
)
console = Console()


@rag_app.command("build")
def build_command() -> None:
    """Build a clean workspace vector index from scratch."""
    console.print("[bold yellow]Building workspace vector index from scratch...[/bold yellow]")
    console.print("[dim]Scanning and chunking codebase files (this might take a moment)...[/dim]")

    indexer = get_indexer()
    if indexer is None:
        console.print("[bold red]RAG is disabled in configuration. Please check your RAG_ENABLED setting.[/bold red]")
        raise typer.Exit(1)

    try:
        indexer.build()
        console.print(
            Panel(
                "[bold green]Successfully built workspace RAG vector index![/bold green]\n"
                f"Index location: `{indexer.vector_store.db_path}`",
                title="RAG Index Build",
                border_style="green",
            )
        )
    except Exception as e:
        console.print(f"[bold red]Failed to build index: {e}[/bold red]")
        raise typer.Exit(1) from e


@rag_app.command("refresh")
def refresh_command() -> None:
    """Incrementally refresh the workspace index with modifications/new files."""
    console.print("[bold yellow]Refreshing workspace vector index...[/bold yellow]")

    indexer = get_indexer()
    if indexer is None:
        console.print("[bold red]RAG is disabled in configuration. Please check your RAG_ENABLED setting.[/bold red]")
        raise typer.Exit(1)

    try:
        indexer.refresh()
        console.print(
            Panel(
                "[bold green]Successfully synchronized and refreshed RAG index![/bold green]",
                title="RAG Index Refresh",
                border_style="green",
            )
        )
    except Exception as e:
        console.print(f"[bold red]Failed to refresh index: {e}[/bold red]")
        raise typer.Exit(1) from e


@rag_app.command("clear")
def clear_command() -> None:
    """Wipe all indexed chunks from the workspace database."""
    confirm = typer.confirm("Are you sure you want to delete the local workspace vector database?")
    if not confirm:
        console.print("[yellow]Aborted.[/yellow]")
        return

    store = get_vector_store()
    if store is None:
        console.print("[bold red]RAG is disabled in configuration.[/bold red]")
        raise typer.Exit(1)

    try:
        store.clear()
        console.print(
            Panel(
                "[bold green]Successfully cleared all RAG index collections![/bold green]",
                title="RAG Clear",
                border_style="green",
            )
        )
    except Exception as e:
        console.print(f"[bold red]Failed to clear RAG database: {e}[/bold red]")
        raise typer.Exit(1) from e
