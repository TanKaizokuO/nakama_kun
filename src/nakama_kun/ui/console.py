"""
ui/console.py — Shared Rich Console instance for nakama_kun.

A single ``Console`` is created here and imported everywhere that needs to
print to the terminal.  This guarantees:

* Consistent styling across all modules.
* A single capture target for unit-testing output.
* One place to configure width, force_terminal, etc.

Phase 3+: swap the console for a logging-aware wrapper that tees output
to a structured log file alongside terminal output.
"""

from rich.console import Console

# ---------------------------------------------------------------------------
# Shared terminal console
# ---------------------------------------------------------------------------

#: The single, application-wide Rich console.
#: Import this instead of constructing a new Console() in each module.
console: Console = Console()


def prompt_continue() -> None:
    """
    Block until the user presses Enter, then clear the prompt line.

    Call this at the end of any leaf mode that only displays a result panel,
    so the panel stays visible long enough for the user to read it before the
    parent menu re-renders on top.

    Handles Ctrl-C / Ctrl-D silently (just returns).
    """
    try:
        console.print("[dim]  Press [bold]Enter[/bold] to continue…[/dim]")
        input()
    except (KeyboardInterrupt, EOFError):
        pass


__all__ = ["console", "prompt_continue"]
