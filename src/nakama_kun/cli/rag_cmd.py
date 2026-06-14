from __future__ import annotations

import typer
import os
from pathlib import Path
from rich.console import Console
from rich.panel import Panel

from nakama_kun.rag import get_indexer, get_vector_store

rag_app = typer.Typer(
    name="rag",
    help="Manage and query the workspace vector index (RAG).",
    no_args_is_help=True,
)
console = Console()


@rag_app.command("index")
def index_command() -> None:
    """Incrementally refresh the workspace index with modifications/new files."""
    console.print("[bold yellow]Running incremental RAG indexing check...[/bold yellow]")
    console.print("[dim]Scanning codebase files and memory records for updates...[/dim]")

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


@rag_app.command("rebuild")
def rebuild_command() -> None:
    """Build a clean workspace vector index from scratch."""
    console.print("[bold yellow]Building workspace vector index from scratch...[/bold yellow]")
    console.print("[dim]Scanning and chunking codebase files and memory records...[/dim]")

    indexer = get_indexer()
    if indexer is None:
        console.print("[bold red]RAG is disabled in configuration. Please check your RAG_ENABLED setting.[/bold red]")
        raise typer.Exit(1)

    try:
        indexer.build()
        console.print(
            Panel(
                "[bold green]Successfully built workspace RAG vector index![/bold green]\n"
                f"Index location: `{indexer.rag_dir}`",
                title="RAG Rebuild",
                border_style="green",
            )
        )
    except Exception as e:
        console.print(f"[bold red]Failed to build index: {e}[/bold red]")
        raise typer.Exit(1) from e


@rag_app.command("stats")
def stats_command() -> None:
    """Display statistics about the workspace index database."""
    indexer = get_indexer()
    if indexer is None:
        console.print("[bold red]RAG is disabled in configuration.[/bold red]")
        raise typer.Exit(1)

    try:
        # Load metadata
        meta = indexer.metadata_manager.load()
        
        # Get document and chunk counts from documents.db
        docs = indexer.metadata_store.list_documents()
        total_docs = len(docs)
        total_chunks = sum(d.chunk_count for d in docs)
        
        # Breakdown by type
        type_counts = {}
        for d in docs:
            type_counts[d.type] = type_counts.get(d.type, 0) + 1

        # Check DB sizes
        def get_dir_size(path: Path) -> int:
            total = 0
            if path.is_file():
                return path.stat().st_size
            for root, dirs, files in os.walk(path):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        total += os.path.getsize(fp)
                    except OSError:
                        pass
            return total

        chroma_size = get_dir_size(indexer.chroma_dir)
        sqlite_size = get_dir_size(indexer.sqlite_db_path) if indexer.sqlite_db_path.exists() else 0
        
        console.print("[bold cyan]=== Nakama-kun RAG Index Statistics ===[/bold cyan]")
        console.print(f"Index Root: [dim]{indexer.rag_dir}[/dim]")
        console.print(f"Chroma DB Path: [dim]{indexer.chroma_dir}[/dim] ({chroma_size / 1024:.1f} KB)")
        console.print(f"Metadata DB Path: [dim]{indexer.sqlite_db_path}[/dim] ({sqlite_size / 1024:.1f} KB)")
        console.print(f"Embedding Model: [green]{meta.get('embedding_model', 'BGE-M3')}[/green]")
        console.print(f"Last Indexed: [green]{meta.get('last_indexed_at', 'Never')}[/green]")
        console.print(f"Total Documents: [bold green]{total_docs}[/bold green]")
        console.print(f"Total Chunks: [bold green]{total_chunks}[/bold green]")
        
        if type_counts:
            console.print("\n[bold]Document Breakdown by Type:[/bold]")
            for t, count in sorted(type_counts.items()):
                console.print(f"  - {t}: [green]{count}[/green]")
                
    except Exception as e:
        console.print(f"[bold red]Failed to get stats: {e}[/bold red]")
        raise typer.Exit(1) from e


@rag_app.command("clear")
def clear_command() -> None:
    """Wipe all indexed chunks from the workspace database."""
    confirm = typer.confirm("Are you sure you want to delete the local workspace vector database?")
    if not confirm:
        console.print("[yellow]Aborted.[/yellow]")
        return

    store = get_vector_store()
    indexer = get_indexer()
    if store is None or indexer is None:
        console.print("[bold red]RAG is disabled in configuration.[/bold red]")
        raise typer.Exit(1)

    try:
        store.clear()
        indexer.metadata_store.clear()
        if indexer.metadata_path.exists():
            indexer.metadata_path.unlink()
        console.print(
            Panel(
                "[bold green]Successfully cleared all RAG index collections and metadata![/bold green]",
                title="RAG Clear",
                border_style="green",
            )
        )
    except Exception as e:
        console.print(f"[bold red]Failed to clear RAG database: {e}[/bold red]")
        raise typer.Exit(1) from e
