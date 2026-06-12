import asyncio
from typing import Any

import questionary
from rich.console import Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from nakama_kun.ai.exceptions import (
    AIError,
    APIKeyNotFoundError,
    InvalidModelError,
    NetworkError,
    RateLimitError,
)
from nakama_kun.ai.models.plan import Plan
from nakama_kun.ai.services.chat_service import ChatService
from nakama_kun.ai.services.planner_service import PlannerService
from nakama_kun.core.constants import APP_VERSION, Colours, NavSignal
from nakama_kun.modes.base import BaseMode
from nakama_kun.ui.console import console
from nakama_kun.ui.menus import _MENU_STYLE


class PlanMode(BaseMode):
    """Plan Mode — LLM-driven task planning and decomposition.

    This mode operates purely as a reasoning and planning layer, providing
    structured plans without executing code or modifying files.
    """

    name: str = "Plan Mode"

    def __init__(self, chat_service: ChatService) -> None:
        self._chat_service = chat_service
        self._planner_service = PlannerService(chat_service)

    def run(self) -> NavSignal:
        try:
            return asyncio.run(self._run_async())
        except KeyboardInterrupt:
            console.print("\n[yellow]Returning to menu...[/yellow]")
            return NavSignal.BACK

    async def _run_async(self) -> NavSignal:
        console.print()
        console.print(
            Panel(
                Text(
                    "nakama_kun Plan Mode\n"
                    "Describe your implementation goal, or type 'back'/'exit' to return.",
                    style=f"bold {Colours.PLAN}",
                    justify="center",
                ),
                border_style=Colours.PLAN,
                title="Plan Mode",
                subtitle=f"v{APP_VERSION}",
            )
        )

        from nakama_kun.memory import get_memory_repository
        repo = get_memory_repository()
        conversation_id = None
        try:
            latest = repo.get_latest_conversation("plan")
            if latest:
                conversation_id = latest["id"]
                self._planner_service.history = repo.get_messages(conversation_id)
                console.print(
                    f"[dim]Restored active planning session: {latest['title']} ({len(self._planner_service.history)} messages)[/dim]\n"
                )
            else:
                conversation_id = repo.create_conversation("CLI Plan Session", "plan")
        except Exception as e:
            from loguru import logger
            logger.warning(f"Failed to load memory: {e}")

        while True:
            try:
                user_msg = await questionary.text(
                    "Goal:", style=_MENU_STYLE
                ).ask_async()

                if user_msg is None:
                    console.print()
                    break

                user_msg = user_msg.strip()
                if not user_msg:
                    continue

                if user_msg.lower() in ("exit", "back"):
                    break

                console.print("\n[bold yellow]nakama_kun Planner:[/bold yellow]")
                console.print(
                    f"[bold dim]Model: "
                    f"{self._chat_service.provider.settings.openrouter_model}"
                    f"[/bold dim]\n"
                )
                console.print("[italic dim]Planning...[/italic dim]")

                plan, raw_text = await self._planner_service.plan(user_msg)

                if plan is not None:
                    self._render_plan(plan)
                else:
                    self._render_unstructured(raw_text)

                console.print()

                if conversation_id:
                    try:
                        if len(self._planner_service.history) >= 2:
                            repo.add_message(conversation_id, self._planner_service.history[-2])
                            repo.add_message(conversation_id, self._planner_service.history[-1])
                    except Exception as e:
                        from loguru import logger
                        logger.warning(f"Failed to save messages to database: {e}")

            except APIKeyNotFoundError:
                console.print("\n[bold red]API key not found.[/bold red]\n")
            except RateLimitError:
                console.print(
                    "\n[bold red]Rate limit exceeded. Try again later.[/bold red]\n"
                )
            except NetworkError:
                console.print("\n[bold red]Unable to reach provider.[/bold red]\n")
            except InvalidModelError:
                console.print(
                    "\n[bold red]Configured model unavailable.[/bold red]\n"
                )
            except AIError as e:
                console.print(f"\n[bold red]AI Error: {e}[/bold red]\n")
            except Exception as e:
                console.print(f"\n[bold red]Unexpected error: {e}[/bold red]\n")

        return NavSignal.BACK

    def _render_plan(self, plan: Plan) -> None:
        """Render a structured Plan model beautifully in the terminal."""
        elements: list[Any] = []

        # Goal Summary
        elements.append(Text("Goal Summary", style=f"bold {Colours.PLAN}"))
        elements.append(Text(plan.goal_summary, style="italic"))
        elements.append(Text(""))

        # File/Module Targets
        if plan.targets:
            elements.append(Text("Target Files/Modules", style="bold cyan"))
            for target in plan.targets:
                elements.append(Text(f"  • {target}"))
            elements.append(Text(""))

        # Assumptions
        if plan.assumptions:
            elements.append(Text("Assumptions", style="bold cyan"))
            for assumption in plan.assumptions:
                elements.append(Text(f"  • {assumption}"))
            elements.append(Text(""))

        # Steps
        if plan.ordered_steps:
            elements.append(Text("Execution Steps", style="bold green"))
            for idx, step in enumerate(plan.ordered_steps, start=1):
                elements.append(Text(f"  {idx}. {step}"))
            elements.append(Text(""))

        # Risks
        if plan.risks:
            elements.append(Text("Risks & Hazards", style="bold red"))
            for risk in plan.risks:
                elements.append(Text(f"  ⚠️ {risk}"))
            elements.append(Text(""))

        # Validation Checklist
        if plan.validation_checklist:
            elements.append(Text("Validation Checklist", style="bold magenta"))
            for item in plan.validation_checklist:
                elements.append(Text(f"  ☐ {item}"))
            elements.append(Text(""))

        group = Group(*elements)
        console.print(
            Panel(
                group,
                title="[bold yellow]📋 Planned Implementation[/bold yellow]",
                border_style="yellow",
                expand=False,
            )
        )

    def _render_unstructured(self, raw_text: str) -> None:
        """Render unstructured Markdown plan output."""
        console.print(
            Panel(
                Markdown(raw_text),
                title="[bold yellow]📋 Implementation Plan[/bold yellow]",
                border_style="yellow",
                expand=False,
            )
        )
