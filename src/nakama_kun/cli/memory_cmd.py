from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from nakama_kun.memory import get_memory_repository
from nakama_kun.memory.noop import NoOpMemoryRepository

memory_app = typer.Typer(
    name="memory",
    help="Manage and inspect Nakama-kun persistent memory.",
    no_args_is_help=True,
)
console = Console()


@memory_app.command("inspect")
def inspect_command() -> None:
    """Inspect stored memory, showing conversations, preferences, and agent tasks."""
    repo = get_memory_repository()

    if isinstance(repo, NoOpMemoryRepository):
        console.print(
            Panel(
                "[yellow]Memory is currently disabled in settings. No records to display.[/yellow]",
                title="Memory Inspection",
                border_style="yellow",
            )
        )
        return

    db_path = getattr(repo, "db_path", "unknown")
    console.print(
        Panel(
            f"[bold cyan]SQLite Memory Database:[/bold cyan] `{db_path}`",
            title="Memory System",
            border_style="cyan",
        )
    )

    # 1. Conversations Table
    convs = repo.get_conversations(limit=10)
    conv_table = Table(title="Recent Conversations", expand=True)
    conv_table.add_column("ID", style="dim", max_width=36)
    conv_table.add_column("Title", style="magenta")
    conv_table.add_column("Mode", style="green")
    conv_table.add_column("Created At", style="yellow")

    for c in convs:
        conv_table.add_row(c["id"], c["title"], c["mode"], c["created_at"])
    console.print(conv_table)
    console.print()

    # 2. Agent Tasks Table
    tasks = repo.list_tasks(limit=10)
    task_table = Table(title="Recent Agent Tasks", expand=True)
    task_table.add_column("ID", style="dim", max_width=36)
    task_table.add_column("Description", style="white")
    task_table.add_column("Status", style="bold green")
    task_table.add_column("Created At", style="yellow")

    for t in tasks:
        status_color = (
            "green"
            if t["status"] == "done"
            else "yellow"
            if t["status"] == "running"
            else "red"
        )
        task_table.add_row(
            t["id"],
            t["task_description"],
            f"[{status_color}]{t['status']}[/{status_color}]",
            t["created_at"],
        )
    console.print(task_table)
    console.print()

    # 3. Preferences Table
    prefs = repo.get_all_preferences()
    pref_table = Table(title="User Preferences", expand=True)
    pref_table.add_column("Key", style="bold cyan")
    pref_table.add_column("Value", style="white")

    for key, val in prefs.items():
        pref_table.add_row(key, val)
    console.print(pref_table)


@memory_app.command("clear")
def clear_command() -> None:
    """Wipe all stored records (conversations, messages, tasks, and preferences)."""
    repo = get_memory_repository()

    if isinstance(repo, NoOpMemoryRepository):
        console.print("[yellow]Memory is disabled. Nothing to clear.[/yellow]")
        return

    confirm = typer.confirm("Are you sure you want to delete all Nakama-kun memory?")
    if not confirm:
        console.print("[yellow]Aborted.[/yellow]")
        return

    try:
        repo.clear_all()
        console.print(
            Panel(
                "[bold green]Successfully wiped the memory database![/bold green]",
                title="Wipe Complete",
                border_style="green",
            )
        )
    except Exception as e:
        console.print(f"[bold red]Failed to clear memory: {e}[/bold red]")
