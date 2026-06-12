from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Update
from telegram.ext import ContextTypes

from nakama_kun.telegram.handlers import (
    ask_handler,
    start_handler,
    status_handler,
)
from nakama_kun.telegram.utils import split_message


def test_split_message() -> None:
    # 1. Short message stays single
    chunks = split_message("hello world", max_length=20)
    assert chunks == ["hello world"]

    # 2. Split by lines / max length
    long_msg = "line1\nline2\nline3"
    chunks = split_message(long_msg, max_length=12)
    assert len(chunks) == 2
    assert "line1\nline2\n" in chunks[0]
    assert "line3" in chunks[1]


@pytest.mark.anyio
@patch("nakama_kun.telegram.handlers.TelegramSettings")
async def test_unauthorized_user_blocked(mock_settings_cls: MagicMock) -> None:
    # Mock settings so 12345 is allowed, but the user chat is 99999 (unauthorized)
    mock_settings = MagicMock()
    mock_settings.telegram_allowed_chat_ids = {12345}
    mock_settings_cls.return_value = mock_settings

    update = MagicMock(spec=Update)
    update.effective_chat = MagicMock()
    update.effective_chat.id = 99999
    update.effective_user = MagicMock()
    update.effective_user.username = "intruder"
    update.message = MagicMock()
    update.message.text = "/start"

    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot = AsyncMock()

    # Call any handler
    await start_handler(update, context)

    # Verify start_handler blocked and sent access denied message
    context.bot.send_message.assert_called_once()
    called_args = context.bot.send_message.call_args[1]
    assert called_args["chat_id"] == 99999
    assert "Access Denied" in called_args["text"]


@pytest.mark.anyio
@patch("nakama_kun.telegram.handlers.TelegramSettings")
async def test_start_handler(mock_settings_cls: MagicMock) -> None:
    mock_settings = MagicMock()
    mock_settings.telegram_allowed_chat_ids = {12345}
    mock_settings_cls.return_value = mock_settings

    update = MagicMock(spec=Update)
    update.effective_chat = MagicMock()
    update.effective_chat.id = 12345
    update.effective_user = MagicMock()
    update.effective_user.username = "valid_user"

    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot = AsyncMock()

    await start_handler(update, context)

    context.bot.send_message.assert_called_once()
    called_args = context.bot.send_message.call_args[1]
    assert called_args["chat_id"] == 12345
    assert "Welcome" in called_args["text"]


@pytest.mark.anyio
@patch("nakama_kun.telegram.handlers.TelegramSettings")
async def test_status_handler(mock_settings_cls: MagicMock) -> None:
    mock_settings = MagicMock()
    mock_settings.telegram_allowed_chat_ids = {12345}
    mock_settings_cls.return_value = mock_settings

    update = MagicMock(spec=Update)
    update.effective_chat = MagicMock()
    update.effective_chat.id = 12345
    update.effective_user = MagicMock()

    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot = AsyncMock()

    await status_handler(update, context)

    context.bot.send_message.assert_called_once()
    called_args = context.bot.send_message.call_args[1]
    assert called_args["chat_id"] == 12345
    assert "Status" in called_args["text"]


@pytest.mark.anyio
@patch("nakama_kun.telegram.handlers.TelegramSettings")
@patch("nakama_kun.telegram.handlers._run_ask_logic")
async def test_ask_handler_no_args(mock_run_ask: MagicMock, mock_settings_cls: MagicMock) -> None:
    mock_settings = MagicMock()
    mock_settings.telegram_allowed_chat_ids = {12345}
    mock_settings_cls.return_value = mock_settings

    update = MagicMock(spec=Update)
    update.effective_chat = MagicMock()
    update.effective_chat.id = 12345
    update.effective_user = MagicMock()

    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot = AsyncMock()
    context.args = []  # No args

    await ask_handler(update, context)

    # Should show usage help instead of calling ask logic
    context.bot.send_message.assert_called_once_with(
        chat_id=12345,
        text="⚠️ Usage: `/ask <your question>`",
        parse_mode="Markdown",
    )
    mock_run_ask.assert_not_called()


@pytest.mark.anyio
@patch("nakama_kun.telegram.handlers.TelegramSettings")
@patch("nakama_kun.telegram.handlers._run_ask_logic")
async def test_ask_handler_with_args(mock_run_ask: MagicMock, mock_settings_cls: MagicMock) -> None:
    mock_settings = MagicMock()
    mock_settings.telegram_allowed_chat_ids = {12345}
    mock_settings_cls.return_value = mock_settings

    update = MagicMock(spec=Update)
    update.effective_chat = MagicMock()
    update.effective_chat.id = 12345
    update.effective_user = MagicMock()

    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = ["what", "is", "python?"]

    await ask_handler(update, context)

    mock_run_ask.assert_called_once_with("what is python?", update, context)
