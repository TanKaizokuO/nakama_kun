"""
modes/telegram_mode.py — Telegram Mode for nakama_kun.

Displays the "Telegram Mode Selected" confirmation panel.

Phase 7 extension points (Telegram Bot)
-----------------------------------------
The actual Telegram bot integration will live in:

    integrations/
    └── telegram/
        ├── bot.py          ← python-telegram-bot or aiogram bot factory
        ├── handlers.py     ← message / command handlers
        ├── dispatcher.py   ← wires handlers to the bot
        └── auth.py         ← user allow-list / admin guard

TelegramMode.run() will call ``dispatcher.start_polling()`` (async) or
block on ``bot.run_polling()`` from the python-telegram-bot library.

Environment variables needed (Phase 7):
    TELEGRAM_BOT_TOKEN  — bot token from @BotFather
    TELEGRAM_ADMIN_ID   — numeric user ID allowed to send commands
"""

from __future__ import annotations

from rich.panel import Panel
from rich.text import Text

from nakama_kun.core.constants import Colours, NavSignal
from nakama_kun.modes.base import BaseMode
from nakama_kun.ui.console import console, prompt_continue


class TelegramMode(BaseMode):
    """
    Telegram Mode — runs the nakama_kun Telegram bot.

    Phase 2: confirmation stub.
    Phase 7: full async bot with command handlers and AI integration.
    """

    name: str = "Telegram Mode"

    def run(self) -> NavSignal:
        """Initialize and run the Telegram bot polling loop until stopped."""
        console.print()
        console.print(
            Panel(
                Text("Telegram Mode Starting...", style=f"bold {Colours.TELEGRAM}", justify="center"),
                border_style=Colours.TELEGRAM,
                padding=(0, 4),
            )
        )

        import asyncio

        from nakama_kun.config.telegram import TelegramSettings
        from nakama_kun.telegram.service import TelegramService

        try:
            settings = TelegramSettings()
            if not settings.telegram_bot_token:
                console.print(
                    "[bold red]Error: TELEGRAM_BOT_TOKEN environment variable is not set.[/bold red]"
                )
                console.print("[dim]Please set TELEGRAM_BOT_TOKEN in your .env file.[/dim]\n")
                prompt_continue()
                return NavSignal.BACK

            if not settings.telegram_allowed_chat_ids:
                console.print(
                    "[bold yellow]Warning: TELEGRAM_ALLOWED_CHAT_IDS is empty. No one will be authorized to access the bot.[/bold yellow]"
                )

            service = TelegramService(settings)

            async def bot_runner() -> None:
                await service.start()
                console.print(
                    Panel(
                        Text("Telegram Bot is running! Press Ctrl-C to stop.", style="bold green", justify="center"),
                        border_style="green",
                        padding=(0, 4),
                    )
                )
                while service.is_running:
                    await asyncio.sleep(1)

            try:
                asyncio.run(bot_runner())
            except KeyboardInterrupt:
                console.print("\n[yellow]Stopping Telegram bot...[/yellow]")
                async def shutdown() -> None:
                    await service.stop()
                asyncio.run(shutdown())
                console.print("[green]Telegram bot stopped cleanly.[/green]\n")

        except Exception as exc:
            console.print(f"[bold red]Unexpected error starting Telegram bot: {exc}[/bold red]\n")
            prompt_continue()

        return NavSignal.BACK
