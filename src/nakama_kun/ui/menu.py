"""
menu.py — Interactive main menu for nakama_kun.

Uses Questionary for arrow-key navigation and Rich for status/result
messages.  The menu drives the top-level mode selection (CLI / Telegram /
Exit) and returns a typed :class:`MenuChoice` so callers can branch cleanly
without string comparisons.

Phase 2 extension: add new entries to ``MENU_CHOICES`` and register their
handlers in :func:`handle_menu_choice`.
"""

from __future__ import annotations

from enum import StrEnum

import questionary
from questionary import Style as QStyle
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()

# ---------------------------------------------------------------------------
# Questionary theme — matches the cyan/magenta banner palette
# ---------------------------------------------------------------------------
_MENU_STYLE = QStyle(
    [
        ("qmark", "fg:#00ffff bold"),
        ("question", "fg:#ffffff bold"),
        ("answer", "fg:#00ffff bold"),
        ("pointer", "fg:#ff00ff bold"),
        ("highlighted", "fg:#ff00ff bold"),
        ("selected", "fg:#00ff88"),
        ("separator", "fg:#555555"),
        ("instruction", "fg:#555555 italic"),
        ("text", "fg:#cccccc"),
        ("disabled", "fg:#555555 italic"),
    ]
)


# ---------------------------------------------------------------------------
# Menu choices — extend this enum in Phase 2
# ---------------------------------------------------------------------------
class MenuChoice(StrEnum):
    """
    Strongly-typed representation of every top-level menu option.

    Adding a new mode in Phase 2 means:
    1. Add a member here.
    2. Add a handler in :func:`handle_menu_choice`.
    3. Add the label to ``MENU_CHOICES`` below.
    """

    CLI = "CLI"
    TELEGRAM = "Telegram"
    EXIT = "Exit"


# Human-readable labels ordered as they appear in the menu
MENU_CHOICES: list[str] = [
    MenuChoice.CLI.value,
    MenuChoice.TELEGRAM.value,
    MenuChoice.EXIT.value,
]


def show_main_menu() -> MenuChoice | None:
    """
    Render the interactive mode-selection menu and return the user's pick.

    Uses Questionary's ``select`` prompt so the user can navigate with the
    arrow keys and confirm with Enter.

    Returns:
        The selected :class:`MenuChoice`, or ``None`` if the user interrupted
        the prompt (Ctrl-C / Ctrl-D).
    """
    console.print(
        Panel(
            Text("Choose Mode", style="bold white", justify="center"),
            border_style="bright_cyan",
            padding=(0, 2),
        )
    )

    try:
        raw: str | None = questionary.select(
            "",  # Label already shown via Rich Panel above
            choices=MENU_CHOICES,
            style=_MENU_STYLE,
            use_shortcuts=False,
            use_arrow_keys=True,
        ).ask()
    except (KeyboardInterrupt, EOFError):
        return None

    if raw is None:
        return None

    return MenuChoice(raw)


def handle_menu_choice(choice: MenuChoice) -> bool:
    """
    Execute the action associated with *choice* and return whether the app
    should keep running.

    Args:
        choice: The user's selected :class:`MenuChoice`.

    Returns:
        ``True``  — keep the main loop running.
        ``False`` — exit the application.

    Phase 2: Replace the stub ``console.print`` calls with real dispatcher
    invocations (e.g. ``cli_runner.start()``, ``telegram_runner.start()``).
    """
    match choice:
        case MenuChoice.CLI:
            _handle_cli()
            return True

        case MenuChoice.TELEGRAM:
            _handle_telegram()
            return True

        case MenuChoice.EXIT:
            _handle_exit()
            return False

        case _:
            console.print(
                f"[bold red]Unknown selection: {choice!r}[/bold red]"
            )
            return True


# ---------------------------------------------------------------------------
# Individual mode stubs — replace with real implementations in Phase 2
# ---------------------------------------------------------------------------


def _handle_cli() -> None:
    """
    CLI mode stub.

    Phase 2 sub-modes:
    - Agent Mode
    - Plan Mode
    - Ask Mode
    """
    console.print()
    console.print(
        Panel(
            Text("Starting CLI mode...", style="bold bright_green", justify="center"),
            border_style="green",
            padding=(0, 4),
        )
    )
    console.print()


def _handle_telegram() -> None:
    """
    Telegram mode stub.

    Phase 2 sub-modes:
    - Telegram Bot integration
    """
    console.print()
    console.print(
        Panel(
            Text(
                "Starting Telegram mode...",
                style="bold bright_blue",
                justify="center",
            ),
            border_style="blue",
            padding=(0, 4),
        )
    )
    console.print()


def _handle_exit() -> None:
    """Display a farewell message before the application terminates."""
    console.print()
    console.print(
        Panel(
            Text("Goodbye! 👋", style="bold bright_magenta", justify="center"),
            border_style="magenta",
            padding=(0, 4),
        )
    )
    console.print()
