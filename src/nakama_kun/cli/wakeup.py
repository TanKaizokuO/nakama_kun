"""
cli/wakeup.py — The ``nakama_kun wakeup`` command for Phase 2.

Phase 2 changes vs Phase 1
---------------------------
* Constructs the :class:`~nakama_kun.core.router.Router` and registers all
  top-level modes.
* Delegates the menu loop to the router rather than calling UI functions
  directly.
* Raises clear errors on misconfiguration (unregistered mode name typo).

Responsibilities (intentionally thin):
1. Load application config.
2. Display the ASCII startup banner.
3. Build and start the router.
4. Handle Ctrl-C / unexpected exceptions gracefully.
"""

from __future__ import annotations

import sys

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from nakama_kun.ai.config import AISettings
from nakama_kun.ai.providers.openrouter_provider import OpenRouterProvider
from nakama_kun.ai.services.chat_service import ChatService
from nakama_kun.config import get_default_config
from nakama_kun.core.constants import APP_VERSION, CURRENT_PHASE, NavSignal
from nakama_kun.core.router import Router
from nakama_kun.modes.agent_mode import AgentMode
from nakama_kun.modes.ask_mode import AskMode
from nakama_kun.modes.cli_mode import CLIMode
from nakama_kun.modes.plan_mode import PlanMode
from nakama_kun.modes.telegram_mode import TelegramMode
from nakama_kun.ui.banner import display_banner
from nakama_kun.ui.menus import MainMenuChoice, show_main_menu

console = Console()


# ---------------------------------------------------------------------------
# Public Typer command
# ---------------------------------------------------------------------------


def wakeup_command() -> None:
    """
    Wake up nakama_kun and launch the interactive multi-mode terminal UI.

    This is the Phase 2 entry point.  It:
    1. Loads application config.
    2. Renders the startup banner.
    3. Constructs the central Router and registers all top-level modes.
    4. Runs the main menu loop, delegating each selection to the router.

    Example::

        $ nakama_kun wakeup
    """
    config = get_default_config()

    # Preload RAG models on application startup
    try:
        from nakama_kun.rag.model_manager import preload_rag_models
        preload_rag_models()
    except Exception as e:
        from loguru import logger
        logger.error(f"Failed to preload RAG models: {e}")

    try:
        # 1. Banner
        display_banner(
            app_name="nakama kun",
            subtitle=f"{CURRENT_PHASE}  |  {config.app_name}",
            version=f"v{APP_VERSION}",
        )

        # 2. Build and start the router
        router = _build_router()
        _run_router_loop(router)

    except KeyboardInterrupt:
        _graceful_interrupt()
    except Exception as exc:  # noqa: BLE001
        _handle_unexpected_error(exc)


# ---------------------------------------------------------------------------
# Router construction
# ---------------------------------------------------------------------------


def _build_router() -> Router:
    """
    Construct and return a fully-configured Router.

    All top-level modes are registered here.

    Returns:
        A :class:`~nakama_kun.core.router.Router` ready to run.
    """
    router = Router()

    # Phase 3 Dependency Injection
    settings = AISettings()
    provider = OpenRouterProvider(settings)
    chat_service = ChatService(provider)

    agent_mode = AgentMode(chat_service)
    plan_mode = PlanMode(chat_service)
    ask_mode = AskMode(chat_service)

    # CLI mode acts as a sub-router orchestrator holding child modes
    cli_mode = CLIMode(agent_mode, plan_mode, ask_mode)
    telegram_mode = TelegramMode()

    # Register top-level modes (order matches MAIN_MENU_CHOICES)
    router.register("cli", cli_mode)
    router.register("telegram", telegram_mode)

    return router


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def _run_router_loop(router: Router) -> None:
    """
    Show the top-level menu and dispatch each selection via the router.

    The loop continues until:
    * The user selects "Exit".
    * A mode returns :attr:`~nakama_kun.core.constants.NavSignal.EXIT`.
    * The user presses Ctrl-C (handled in the caller).

    Args:
        router: The configured :class:`~nakama_kun.core.router.Router`.
    """
    while True:
        choice = show_main_menu()

        # Ctrl-C / Ctrl-D inside the top-level menu
        if choice is None:
            _graceful_interrupt()
            return

        signal = _dispatch_top_level(router, choice)

        if signal == NavSignal.EXIT:
            _handle_exit()
            return

        # NavSignal.BACK at the top level → loop back to the main menu


def _dispatch_top_level(router: Router, choice: MainMenuChoice) -> NavSignal:
    """
    Map a top-level :class:`~nakama_kun.ui.menus.MainMenuChoice` to a router action.

    Args:
        router: Active Router instance.
        choice: The user's menu selection.

    Returns:
        The :class:`~nakama_kun.core.constants.NavSignal` for the caller.
    """
    match choice:
        case MainMenuChoice.CLI:
            return router.launch("cli")

        case MainMenuChoice.TELEGRAM:
            return router.launch("telegram")

        case MainMenuChoice.EXIT:
            return NavSignal.EXIT

        case _:
            console.print(f"[bold red]Unknown selection: {choice!r}[/bold red]")
            return NavSignal.CONTINUE


# ---------------------------------------------------------------------------
# Exit / error helpers
# ---------------------------------------------------------------------------


def _handle_exit() -> None:
    """Display the farewell panel and terminate cleanly."""
    console.print()
    console.print(
        Panel(
            Text("Goodbye! 👋", style="bold bright_magenta", justify="center"),
            border_style="magenta",
            padding=(0, 4),
        )
    )
    console.print()
    sys.exit(0)


def _graceful_interrupt() -> None:
    """Handle Ctrl-C with a polite exit message."""
    console.print()
    console.print("[bold yellow]Interrupted — see you later! 👋[/bold yellow]")
    console.print()
    sys.exit(0)


def _handle_unexpected_error(exc: Exception) -> None:
    """
    Log an unexpected exception and exit with a non-zero status code.

    Phase 3: forward to a structured logger / Sentry.
    """
    console.print()
    console.print(f"[bold red]Unexpected error:[/bold red] {exc}")
    console.print("[dim]Run with --debug for a full traceback.[/dim]")
    console.print()
    sys.exit(1)
