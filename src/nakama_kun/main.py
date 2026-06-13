"""
main.py — Top-level Typer application for nakama_kun (Phase 2).

This module owns the ``app`` Typer instance and registers all commands.
Business logic lives in ``cli/commands.py`` and the ``modes/`` sub-package,
not here.

Adding a new Phase 3+ command is a single line:

    from nakama_kun.cli.commands import agent_command
    app.command(name="agent")(agent_command)

Note on Typer single-command behaviour
---------------------------------------
Typer normally promotes a single registered command to the root, hiding the
sub-command name.  We prevent this with a root ``@app.callback`` that does
nothing — its presence forces Typer to keep children as true sub-commands
so ``nakama_kun wakeup`` works as documented.
"""

from __future__ import annotations

import typer

from nakama_kun.cli.commands import (
    explain_command,
    mcp_app,
    memory_app,
    rag_app,
    wakeup_command,
    web_command,
)
from nakama_kun.cli.list_dir import list_directory

# ---------------------------------------------------------------------------
# Typer application
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="nakama_kun",
    help=(
        "An OpenClaw-style AI Agent CLI — your nakama in the terminal.\n\n"
        "Run [bold cyan]nakama_kun wakeup[/bold cyan] to get started."
    ),
    add_completion=False,
    rich_markup_mode="rich",
    pretty_exceptions_enable=True,
    pretty_exceptions_show_locals=False,
    no_args_is_help=True,
    invoke_without_command=True,
)


@app.callback()
def _root_callback(ctx: typer.Context) -> None:
    """
    Root callback — forces Typer to keep sub-commands visible.

    Without this, a single-command Typer app collapses the sub-command
    name and routes directly to the command function.
    """


# ---------------------------------------------------------------------------
# Registered commands
# ---------------------------------------------------------------------------

app.command(
    name="wakeup",
    help="Wake up nakama_kun and launch the interactive multi-mode UI.",
)(wakeup_command)

app.command(
    name="explain",
    help="Analyze the current workspace and print a structural explanation.",
)(explain_command)

app.add_typer(memory_app, name="memory")
app.add_typer(rag_app, name="rag")
app.add_typer(mcp_app, name="mcp")
app.command(
    name="web",
    help="Launch the browser-based graphical web interface.",
)(web_command)

app.command(
    name="list-directory",
    help="List the contents of a given directory.",
)(list_directory)

# ---------------------------------------------------------------------------
# Phase 3+ extension points — uncomment as phases are implemented:
# ---------------------------------------------------------------------------

# from nakama_kun.cli.commands import agent_command
# app.command(name="agent", help="Run a single-shot agentic task.")(agent_command)

# from nakama_kun.cli.commands import plan_command
# app.command(name="plan", help="Generate a task plan for a goal.")(plan_command)

# from nakama_kun.cli.commands import ask_command
# app.command(name="ask", help="Ask a one-off question and exit.")(ask_command)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Package-level entry point invoked by the pyproject.toml script."""
    app()


if __name__ == "__main__":
    main()
