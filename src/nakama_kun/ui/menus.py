"""
ui/menus.py — All interactive menus for nakama_kun Phase 2.

This module owns:
* The shared Questionary theme (``_MENU_STYLE``).
* The top-level mode-selection menu (:func:`show_main_menu`).
* The CLI sub-mode menu (:func:`show_cli_menu`).
* Typed enums for every menu choice to eliminate string comparisons.

Extending in future phases
---------------------------
Add a new enum member + a new ``show_*_menu()`` function following the same
pattern.  No changes to existing functions are needed.

Phase 5 (Planner): add ``show_plan_menu()`` with task breakdown options.
Phase 7 (Telegram): the bot has its own command router; no new menu needed.
"""

from __future__ import annotations

from enum import StrEnum

import questionary
from questionary import Style as QStyle
from rich.panel import Panel
from rich.text import Text

from nakama_kun.ui.console import console

# ---------------------------------------------------------------------------
# Shared Questionary theme — cyan / magenta palette matching the banner
# ---------------------------------------------------------------------------

_MENU_STYLE = QStyle(
    [
        ("qmark",       "fg:#00ffff bold"),
        ("question",    "fg:#ffffff bold"),
        ("answer",      "fg:#00ffff bold"),
        ("pointer",     "fg:#ff00ff bold"),
        ("highlighted", "fg:#ff00ff bold"),
        ("selected",    "fg:#00ff88"),
        ("separator",   "fg:#555555"),
        ("instruction", "fg:#555555 italic"),
        ("text",        "fg:#cccccc"),
        ("disabled",    "fg:#555555 italic"),
    ]
)


# ---------------------------------------------------------------------------
# Top-level menu
# ---------------------------------------------------------------------------

class MainMenuChoice(StrEnum):
    """
    Strongly-typed top-level menu options.

    Extend here for Phase 7 when more top-level integrations are added.
    """

    CLI      = "CLI"
    TELEGRAM = "Telegram"
    EXIT     = "Exit"


_MAIN_MENU_CHOICES: list[str] = [
    MainMenuChoice.CLI.value,
    MainMenuChoice.TELEGRAM.value,
    MainMenuChoice.EXIT.value,
]


def show_main_menu() -> MainMenuChoice | None:
    """
    Render the top-level "Choose Mode" menu and return the user's selection.

    Returns:
        The selected :class:`MainMenuChoice`, or ``None`` on Ctrl-C / Ctrl-D.
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
            "",
            choices=_MAIN_MENU_CHOICES,
            style=_MENU_STYLE,
            use_shortcuts=False,
            use_arrow_keys=True,
        ).ask()
    except (KeyboardInterrupt, EOFError):
        return None

    return MainMenuChoice(raw) if raw is not None else None


# ---------------------------------------------------------------------------
# CLI sub-menu
# ---------------------------------------------------------------------------

class CLIMenuChoice(StrEnum):
    """
    Strongly-typed CLI sub-mode options.

    Phase 3+: add ``MEMORY``, ``CONTEXT``, etc. as new sub-modes appear.
    """

    AGENT = "Agent Mode"
    PLAN  = "Plan Mode"
    ASK   = "Ask Mode"
    EXPLAIN = "Explain Project"
    MEMORY = "Memory Actions"
    BACK  = "Back"


_CLI_MENU_CHOICES: list[str] = [
    CLIMenuChoice.AGENT.value,
    CLIMenuChoice.PLAN.value,
    CLIMenuChoice.ASK.value,
    CLIMenuChoice.EXPLAIN.value,
    CLIMenuChoice.MEMORY.value,
    CLIMenuChoice.BACK.value,
]


def show_cli_menu() -> CLIMenuChoice | None:
    """
    Render the "Choose CLI Mode" sub-menu and return the user's selection.

    Returns:
        The selected :class:`CLIMenuChoice`, or ``None`` on Ctrl-C / Ctrl-D.
    """
    console.print(
        Panel(
            Text("Choose CLI Mode", style="bold white", justify="center"),
            border_style="green",
            padding=(0, 2),
        )
    )

    try:
        raw: str | None = questionary.select(
            "",
            choices=_CLI_MENU_CHOICES,
            style=_MENU_STYLE,
            use_shortcuts=False,
            use_arrow_keys=True,
        ).ask()
    except (KeyboardInterrupt, EOFError):
        return None

    return CLIMenuChoice(raw) if raw is not None else None
