from __future__ import annotations

from typing import Any

from loguru import logger
from telegram.ext import Application, ApplicationBuilder

from nakama_kun.config.telegram import TelegramSettings


class TelegramService:
    """Manages the lifecycle of the Telegram bot application."""

    def __init__(self, settings: TelegramSettings) -> None:
        self.settings = settings
        self._application: Application[Any, Any, Any, Any, Any, Any] | None = None
        self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    async def start(self) -> None:
        """Initialize and start polling the Telegram bot."""
        if self._is_running:
            logger.warning("Telegram bot is already running.")
            return

        token_str = self.settings.telegram_bot_token.get_secret_value() if self.settings.telegram_bot_token else None
        if not token_str:
            raise ValueError("TELEGRAM_BOT_TOKEN is not set.")

        logger.info("Initializing Telegram bot application...")
        self._application = ApplicationBuilder().token(token_str).build()

        # Set up base handlers
        self._register_handlers()

        await self._application.initialize()
        await self._application.start()
        
        # Start polling
        if self._application.updater:
            await self._application.updater.start_polling()
            logger.info("Telegram bot started polling successfully.")
            self._is_running = True
        else:
            logger.error("Failed to retrieve updater from Application.")

    async def stop(self) -> None:
        """Gracefully stop and clean up the Telegram bot."""
        if not self._is_running or not self._application:
            logger.warning("Telegram bot is not running.")
            return

        logger.info("Stopping Telegram bot...")
        if self._application.updater:
            await self._application.updater.stop()
        
        await self._application.stop()
        await self._application.shutdown()
        self._is_running = False
        logger.info("Telegram bot shutdown complete.")

    def _register_handlers(self) -> None:
        """Register command and message handlers."""
        from telegram.ext import CommandHandler, MessageHandler, filters

        from nakama_kun.telegram.handlers import (
            agent_handler,
            ask_handler,
            message_handler,
            plan_handler,
            start_handler,
            status_handler,
        )

        if self._application:
            self._application.add_handler(CommandHandler("start", start_handler))
            self._application.add_handler(CommandHandler("status", status_handler))
            self._application.add_handler(CommandHandler("ask", ask_handler))
            self._application.add_handler(CommandHandler("plan", plan_handler))
            self._application.add_handler(CommandHandler("agent", agent_handler))
            
            # Plain text message handler
            self._application.add_handler(
                MessageHandler(filters.TEXT & (~filters.COMMAND), message_handler)
            )
            logger.info("Command handlers (/start, /status, /ask, /plan, /agent) and message handler registered.")
