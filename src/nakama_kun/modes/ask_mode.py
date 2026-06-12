import asyncio

import questionary
from rich.live import Live
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
from nakama_kun.ai.services.chat_service import ChatService
from nakama_kun.core.constants import APP_VERSION, Colours, NavSignal
from nakama_kun.modes.base import BaseMode
from nakama_kun.ui.console import console
from nakama_kun.ui.menus import _MENU_STYLE


class AskMode(BaseMode):
    """Ask Mode — conversational interface to the AI backbone.

    Streams response tokens to the terminal and maintains chat history.
    """

    name: str = "Ask Mode"

    def __init__(self, chat_service: ChatService) -> None:
        self._chat_service = chat_service

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
                    "nakama_kun Ask Mode\nType your question, or 'exit' to return.",
                    style=f"bold {Colours.ASK}",
                    justify="center",
                ),
                border_style=Colours.ASK,
                title="Ask Mode",
                subtitle=f"v{APP_VERSION}",
            )
        )

        from nakama_kun.memory import get_memory_repository
        repo = get_memory_repository()
        conversation_id = None
        try:
            latest = repo.get_latest_conversation("ask")
            if latest:
                conversation_id = latest["id"]
                self._chat_service.history = repo.get_messages(conversation_id)
                console.print(
                    f"[dim]Restored active conversation: {latest['title']} ({len(self._chat_service.history)} messages)[/dim]\n"
                )
            else:
                conversation_id = repo.create_conversation("CLI Ask Session", "ask")
        except Exception as e:
            from loguru import logger
            logger.warning(f"Failed to load memory: {e}")

        while True:
            try:
                # Ask user for input using questionary styled prompt
                user_msg = await questionary.text("You:", style=_MENU_STYLE).ask_async()

                # Check for Ctrl-C / Ctrl-D
                if user_msg is None:
                    console.print()
                    break

                user_msg = user_msg.strip()
                if not user_msg:
                    continue

                if user_msg.lower() == "exit":
                    break

                # Update system prompt with fresh workspace context
                from nakama_kun.ai.prompts.system_prompt import ASK_SYSTEM_PROMPT
                from nakama_kun.workspace.context import WorkspaceContextBuilder
                try:
                    workspace_context = WorkspaceContextBuilder().build_summary()
                    self._chat_service.system_prompt = f"{ASK_SYSTEM_PROMPT}\n\n{workspace_context}"
                except Exception:
                    self._chat_service.system_prompt = ASK_SYSTEM_PROMPT

                console.print("\n[bold magenta]nakama_kun:[/bold magenta]")
                console.print(
                    f"[bold dim]Model: {self._chat_service.provider.settings.openrouter_model}[/bold dim]\n"
                )
                console.print("[italic dim]Thinking...[/italic dim]")

                response_text = ""
                with Live(Markdown(""), auto_refresh=False) as live:
                    async for token in self._chat_service.chat_stream(user_msg):
                        response_text += token
                        live.update(Markdown(response_text))
                        live.refresh()
                console.print()  # Print final newline after stream completes

                if conversation_id:
                    try:
                        if len(self._chat_service.history) >= 2:
                            repo.add_message(conversation_id, self._chat_service.history[-2])
                            repo.add_message(conversation_id, self._chat_service.history[-1])
                    except Exception as e:
                        from loguru import logger
                        logger.warning(f"Failed to save messages to database: {e}")

            except APIKeyNotFoundError:
                console.print("\n[bold red]OpenAI API key not found.[/bold red]\n")
            except RateLimitError:
                console.print(
                    "\n[bold red]Rate limit exceeded. Try again later.[/bold red]\n"
                )
            except NetworkError:
                console.print("\n[bold red]Unable to reach provider.[/bold red]\n")
            except InvalidModelError:
                console.print("\n[bold red]Configured model unavailable.[/bold red]\n")
            except AIError as e:
                console.print(f"\n[bold red]AI Error: {e}[/bold red]\n")
            except Exception as e:
                console.print(f"\n[bold red]Unexpected error: {e}[/bold red]\n")

        return NavSignal.BACK
