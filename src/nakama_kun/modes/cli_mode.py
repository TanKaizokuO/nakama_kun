"""
modes/cli_mode.py — CLI Mode orchestrator for nakama_kun.

CLIMode owns the second-level "Choose CLI Mode" menu and dispatches to the
three leaf modes: Agent, Plan, and Ask.

Responsibilities
----------------
* Render the CLI sub-menu (via ``ui.menus.show_cli_menu``).
* Translate the user's selection into a ``NavSignal`` for the Router.
* Delegate actual mode execution to the relevant :class:`BaseMode` subclass.

This pattern keeps CLIMode as a thin orchestrator — it owns navigation but
not business logic.  Each leaf mode is self-contained and independently
testable.

Phase 3+ extension points
--------------------------
* A ``context`` dict (or typed dataclass) can be threaded through to each
  leaf mode so they share session state (AI history, workspace index, etc.).
* CLIMode can grow a ``setup()`` hook that pre-warms the AI client once for
  all sub-modes to share.
"""

from __future__ import annotations

from rich.console import Console

from nakama_kun.core.constants import NavSignal
from nakama_kun.modes.agent_mode import AgentMode
from nakama_kun.modes.ask_mode import AskMode
from nakama_kun.modes.base import BaseMode
from nakama_kun.modes.plan_mode import PlanMode
from nakama_kun.ui.menus import _MENU_STYLE, CLIMenuChoice, show_cli_menu

console = Console()


class CLIMode(BaseMode):
    """
    CLI Mode — hierarchical sub-menu that routes to Agent / Plan / Ask.

    The inner loop runs until the user chooses "Back", which propagates
    NavSignal.BACK up to the top-level Router.
    """

    name: str = "CLI Mode"

    def __init__(
        self, agent_mode: AgentMode, plan_mode: PlanMode, ask_mode: AskMode
    ) -> None:
        self._agent = agent_mode
        self._plan = plan_mode
        self._ask = ask_mode

    def run(self) -> NavSignal:
        """
        Display the CLI sub-menu and dispatch to the selected leaf mode.

        Loops until the user selects "Back" or a leaf mode signals EXIT.

        Returns:
            NavSignal.BACK if the user chose Back.
            NavSignal.EXIT if a sub-mode triggered application exit.
        """
        while True:
            choice = show_cli_menu()

            # Ctrl-C / Ctrl-D inside the sub-menu → back to parent
            if choice is None:
                return NavSignal.BACK

            # "Back" menu item chosen → exit CLI mode immediately
            if choice == CLIMenuChoice.BACK:
                return NavSignal.BACK

            signal = self._dispatch(choice)

            if signal == NavSignal.EXIT:
                return NavSignal.EXIT

            # NavSignal.BACK from a leaf mode → stay in the CLI sub-menu loop
            # (the leaf mode finished; return to "Choose CLI Mode")


    def _dispatch(self, choice: CLIMenuChoice) -> NavSignal:
        """
        Map a CLI menu selection to the appropriate mode and launch it.

        Args:
            choice: The user's selected :class:`~nakama_kun.ui.menus.CLIMenuChoice`.

        Returns:
            The :class:`~nakama_kun.core.constants.NavSignal` from the launched mode.
        """
        match choice:
            case CLIMenuChoice.AGENT:
                return self._agent.run()

            case CLIMenuChoice.PLAN:
                return self._plan.run()

            case CLIMenuChoice.ASK:
                return self._ask.run()

            case CLIMenuChoice.EXPLAIN:
                from rich.markdown import Markdown
                from rich.panel import Panel

                from nakama_kun.workspace.context import WorkspaceContextBuilder

                console.print("\n[bold yellow]Analyzing project...[/bold yellow]")
                builder = WorkspaceContextBuilder()
                summary = builder.build_summary()
                console.print(
                    Panel(
                        Markdown(summary),
                        title="[bold green]Workspace Explanation[/bold green]",
                        border_style="green",
                    )
                )
                console.print()
                return NavSignal.CONTINUE

            case CLIMenuChoice.MEMORY:
                self._handle_memory_actions()
                return NavSignal.CONTINUE

            case CLIMenuChoice.BACK:
                return NavSignal.BACK

            case _:
                console.print(f"[bold red]Unknown CLI selection: {choice!r}[/bold red]")
                return NavSignal.CONTINUE

    def _handle_memory_actions(self) -> None:
        """Render sub-menu options for memory inspection and clearing."""
        import questionary
        from rich.panel import Panel
        from rich.table import Table

        from nakama_kun.memory import get_memory_repository
        from nakama_kun.memory.noop import NoOpMemoryRepository

        repo = get_memory_repository()
        if isinstance(repo, NoOpMemoryRepository):
            console.print(
                Panel(
                    "[yellow]Memory is currently disabled in configuration settings.[/yellow]",
                    border_style="yellow",
                )
            )
            return

        while True:
            try:
                choice = questionary.select(
                    "Memory Actions:",
                    choices=[
                        "Inspect Conversations",
                        "Inspect Tasks",
                        "Inspect Preferences",
                        "Clear All Memory",
                        "Back",
                    ],
                    style=_MENU_STYLE,
                ).ask()
            except (KeyboardInterrupt, EOFError):
                break

            if choice is None or choice == "Back":
                break

            if choice == "Inspect Conversations":
                convs = repo.get_conversations()
                table = Table(title="Recent Conversations", expand=True)
                table.add_column("ID", style="dim", max_width=36)
                table.add_column("Title", style="magenta")
                table.add_column("Mode", style="green")
                table.add_column("Created At", style="yellow")
                for c in convs:
                    table.add_row(c["id"], c["title"], c["mode"], c["created_at"])
                console.print(table)
                console.print()

            elif choice == "Inspect Tasks":
                tasks = repo.list_tasks()
                table = Table(title="Recent Agent Tasks", expand=True)
                table.add_column("ID", style="dim", max_width=36)
                table.add_column("Description", style="white")
                table.add_column("Status", style="bold green")
                table.add_column("Created At", style="yellow")
                for t in tasks:
                    status_color = (
                        "green"
                        if t["status"] == "done"
                        else "yellow"
                        if t["status"] == "running"
                        else "red"
                    )
                    table.add_row(
                        t["id"],
                        t["task_description"],
                        f"[{status_color}]{t['status']}[/{status_color}]",
                        t["created_at"],
                    )
                console.print(table)
                console.print()

            elif choice == "Inspect Preferences":
                prefs = repo.get_all_preferences()
                table = Table(title="User Preferences", expand=True)
                table.add_column("Key", style="bold cyan")
                table.add_column("Value", style="white")
                for k, v in prefs.items():
                    table.add_row(k, v)
                console.print(table)
                console.print()

            elif choice == "Clear All Memory":
                try:
                    confirm = questionary.confirm(
                        "Are you sure you want to delete all saved memory?",
                        default=False,
                        style=_MENU_STYLE,
                    ).ask()
                except (KeyboardInterrupt, EOFError):
                    continue

                if confirm:
                    try:
                        repo.clear_all()
                        console.print(
                            "[bold green]Memory wiped successfully.[/bold green]\n"
                        )
                    except Exception as e:
                        console.print(
                            f"[bold red]Failed to wipe memory: {e}[/bold red]\n"
                        )
