"""
cli/commands.py — Command registry and helper utilities for nakama_kun CLI.

This module is the single place where all Typer commands are defined and
documented.  The ``main.py`` module imports from here; it does not define
business logic itself.

Current commands
----------------
* ``wakeup``   — launch the interactive multi-mode UI (Phase 1 / 2).

Phase 3+ planned commands (uncomment when implemented)
-------------------------------------------------------
* ``agent``    — run a single-shot agent task from the CLI.
* ``plan``     — generate a plan for a given goal.
* ``ask``      — ask a one-off question and exit.
* ``version``  — print version information.

Design decision: why not put commands directly in main.py?
-----------------------------------------------------------
Keeping command implementations here (rather than inlining them in main.py)
allows each command to be tested in isolation via:

    from nakama_kun.cli.commands import agent_command
    agent_command(goal="summarise README.md")

without pulling in the full Typer app.
"""

from __future__ import annotations

from nakama_kun.cli.memory_cmd import memory_app
from nakama_kun.cli.wakeup import wakeup_command

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "wakeup_command",
    "explain_command",
    "memory_app",
    # Phase 3+: add agent_command, plan_command, ask_command here
]

def explain_command() -> None:
    """Analyze the current workspace and print a structural explanation."""
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel

    from nakama_kun.workspace.context import WorkspaceContextBuilder

    console = Console()
    console.print("[bold yellow]Analyzing project...[/bold yellow]")
    try:
        builder = WorkspaceContextBuilder()
        summary = builder.build_summary()
        console.print(
            Panel(
                Markdown(summary),
                title="[bold green]Workspace Explanation[/bold green]",
                border_style="green",
            )
        )
    except Exception as exc:
        console.print(f"[bold red]Failed to analyze project: {exc}[/bold red]")


# ---------------------------------------------------------------------------
# Phase 3+ stubs — uncomment and implement as phases land
# ---------------------------------------------------------------------------

# def agent_command(
#     goal: str = typer.Argument(..., help="Goal for the agent to accomplish."),
#     model: str = typer.Option("gemini-2.0-flash", help="LLM model to use."),
# ) -> None:
#     """Run a single-shot agentic task from the command line."""
#     from nakama_kun.modes.agent_mode import AgentMode
#     AgentMode(goal=goal, model=model).run()


# def plan_command(
#     goal: str = typer.Argument(..., help="Goal to plan for."),
# ) -> None:
#     """Generate a task plan for a given goal."""
#     from nakama_kun.modes.plan_mode import PlanMode
#     PlanMode(goal=goal).run()


# def ask_command(
#     question: str = typer.Argument(..., help="Question to ask the AI."),
# ) -> None:
#     """Ask a single question and print the answer."""
#     from nakama_kun.modes.ask_mode import AskMode
#     AskMode().ask_once(question)
