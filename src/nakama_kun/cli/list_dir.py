from pathlib import Path
import typer
from typing import Optional


def list_directory(path: Path = typer.Argument(..., help="Path to the directory to list")) -> None:
    """List the contents of a given directory."""
    if not path.exists():
        typer.echo(f"Error: Path '{path}' does not exist.", err=True)
        raise typer.Exit(code=1)
    if not path.is_dir():
        typer.echo(f"Error: '{path}' is not a directory.", err=True)
        raise typer.Exit(code=1)

    entries = list(path.iterdir())
    if not entries:
        typer.echo("Directory is empty.")
        return

    for entry in entries:
        if entry.is_dir():
            typer.echo(f"{entry.name}/")  # denote directories with a trailing slash
        else:
            typer.echo(entry.name)