from __future__ import annotations

from loguru import logger
from telegram import Bot


def split_message(text: str, max_length: int = 4000) -> list[str]:
    """Splits a long message into chunks of at most max_length characters.

    Attempts to split on newlines and spaces to keep formatting intact.
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    current_chunk: list[str] = []
    current_length = 0

    lines = text.splitlines(keepends=True)
    for line in lines:
        if len(line) > max_length:
            # If a single line is too long, split it by characters
            if current_chunk:
                chunks.append("".join(current_chunk))
                current_chunk = []
                current_length = 0
            
            # Forced character splitting
            for i in range(0, len(line), max_length):
                chunks.append(line[i : i + max_length])
            continue

        if current_length + len(line) > max_length:
            chunks.append("".join(current_chunk))
            current_chunk = [line]
            current_length = len(line)
        else:
            current_chunk.append(line)
            current_length += len(line)

    if current_chunk:
        chunks.append("".join(current_chunk))

    return chunks


async def send_response_in_chunks(
    bot: Bot,
    chat_id: int,
    text: str,
    status_message_id: int | None = None,
    parse_mode: str = "Markdown",
) -> None:
    """Send text in chunked messages to respect Telegram limits.

    If status_message_id is provided, it edits the status message with the first
    chunk. Subsequent chunks are sent as new messages.
    """
    chunks = split_message(text)
    if not chunks:
        return

    # 1. Handle first chunk (edit status or send)
    first_chunk = chunks[0]
    if status_message_id is not None:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message_id,
                text=first_chunk,
                parse_mode=parse_mode,
            )
        except Exception:
            # Fallback to no parse mode if markdown is invalid
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_message_id,
                    text=first_chunk,
                )
            except Exception as e:
                logger.error(f"Failed to edit status message: {e}")
    else:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=first_chunk,
                parse_mode=parse_mode,
            )
        except Exception:
            await bot.send_message(chat_id=chat_id, text=first_chunk)

    # 2. Handle remaining chunks
    for chunk in chunks[1:]:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=parse_mode,
            )
        except Exception:
            await bot.send_message(chat_id=chat_id, text=chunk)
