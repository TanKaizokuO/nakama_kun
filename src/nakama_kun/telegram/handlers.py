from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from loguru import logger
from telegram import Update
from telegram.ext import ContextTypes

from nakama_kun.config.telegram import TelegramSettings


def authorized_only(
    func: Callable[[Update, ContextTypes.DEFAULT_TYPE], Any]
) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Any]:
    """Decorator to verify the sender is within the authorized whitelisted chat IDs."""

    @wraps(func)
    async def wrapper(
        update: Update, context: ContextTypes.DEFAULT_TYPE, *args: Any, **kwargs: Any
    ) -> Any:
        chat = update.effective_chat
        if not chat:
            logger.warning("Incoming Telegram update has no effective chat.")
            return

        chat_id = chat.id
        settings = TelegramSettings()

        if chat_id not in settings.telegram_allowed_chat_ids:
            logger.warning(
                f"Unauthorized access blocked: Chat ID={chat_id}, User={update.effective_user.username if update.effective_user else 'unknown'}"
            )
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Access Denied: This bot is private and configured for authorized chats only.",
                )
            except Exception as e:
                logger.error(f"Failed to send denial message to chat {chat_id}: {e}")
            return

        logger.info(
            f"Authorized update received: Chat ID={chat_id}, "
            f"User={update.effective_user.username if update.effective_user else 'unknown'}, "
            f"Content={update.message.text if update.message else 'non-text'}"
        )
        return await func(update, context, *args, **kwargs)

    return wrapper


@authorized_only
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message explaining bot commands."""
    welcome_text = (
        "👋 Welcome to *nakama_kun* Telegram Bot!\n\n"
        "Here are the available commands:\n"
        "• `/start` - Display this welcome message\n"
        "• `/status` - Check the bot and AI model status\n"
        "• `/ask <question>` - Ask a general question\n"
        "• `/plan <goal>` - Generate an implementation plan\n"
        "• `/agent <task>` - Run an autonomous agent to accomplish a task\n\n"
        "Any plain text messages will be routed to Ask Mode by default."
    )
    if update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=welcome_text,
            parse_mode="Markdown",
        )


@authorized_only
async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Respond with connection and config details."""
    from nakama_kun.ai.config import AISettings
    settings = AISettings()
    status_text = (
        "🤖 *nakama_kun Status*\n\n"
        "• *System*: Active\n"
        f"• *Model*: `{settings.openrouter_model}`\n"
        "• *API URL*: `https://openrouter.ai/api/v1`"
    )
    if update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=status_text,
            parse_mode="Markdown",
        )


@authorized_only
async def ask_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /ask command."""
    if not update.effective_chat:
        return

    chat_id = update.effective_chat.id

    if not context.args:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ Usage: `/ask <your question>`",
            parse_mode="Markdown",
        )
        return

    question = " ".join(context.args)
    await _run_ask_logic(question, update, context)


@authorized_only
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle plain text chat by routing to Ask mode/logic."""
    if not update.effective_chat or not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    if text.startswith("/"):
        # Commands are handled by command handlers, ignore here
        return

    await _run_ask_logic(text, update, context)


async def _run_ask_logic(
    question: str, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Send question to ChatService and reply to the user."""
    chat_id = update.effective_chat.id  # type: ignore

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text="🤔 _Thinking..._",
        parse_mode="Markdown",
    )

    try:
        from nakama_kun.ai.config import AISettings
        from nakama_kun.ai.prompts.system_prompt import ASK_SYSTEM_PROMPT
        from nakama_kun.ai.providers.openrouter_provider import OpenRouterProvider
        from nakama_kun.ai.services.chat_service import ChatService
        from nakama_kun.memory import get_memory_repository
        from nakama_kun.workspace.context import WorkspaceContextBuilder

        ai_settings = AISettings()
        provider = OpenRouterProvider(ai_settings)
        chat_service = ChatService(provider)

        repo = get_memory_repository()
        pref_key = f"telegram_conv_ask_{chat_id}"
        conversation_id = None
        try:
            conversation_id = repo.get_preference(pref_key)
            if not conversation_id:
                conversation_id = repo.create_conversation(
                    f"Telegram Ask Chat {chat_id}", "telegram_ask"
                )
                repo.save_preference(pref_key, conversation_id)
            chat_service.history = repo.get_messages(conversation_id)
        except Exception as e:
            logger.warning(f"Failed to load Telegram memory: {e}")

        try:
            workspace_context = WorkspaceContextBuilder().build_summary()
            chat_service.system_prompt = (
                f"{ASK_SYSTEM_PROMPT}\n\n{workspace_context}"
            )
        except Exception:
            chat_service.system_prompt = ASK_SYSTEM_PROMPT

        response = await chat_service.chat(question)
        reply = response.content or "No response from AI."

        if conversation_id:
            try:
                if len(chat_service.history) >= 2:
                    repo.add_message(conversation_id, chat_service.history[-2])
                    repo.add_message(conversation_id, chat_service.history[-1])
            except Exception as e:
                logger.warning(f"Failed to save Telegram messages: {e}")

        from nakama_kun.telegram.utils import send_response_in_chunks
        await send_response_in_chunks(
            bot=context.bot,
            chat_id=chat_id,
            text=reply,
            status_message_id=status_msg.message_id,
        )
    except Exception as exc:
        logger.error(f"Error in ask logic: {exc}")
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg.message_id,
                text=f"❌ *Error*: {exc}",
                parse_mode="Markdown",
            )
        except Exception:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg.message_id,
                text=f"❌ Error: {exc}",
            )


@authorized_only
async def plan_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /plan command."""
    if not update.effective_chat:
        return

    chat_id = update.effective_chat.id

    if not context.args:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ Usage: `/plan <goal>`",
            parse_mode="Markdown",
        )
        return

    goal = " ".join(context.args)

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text="📋 _Planning implementation..._",
        parse_mode="Markdown",
    )

    try:
        from nakama_kun.ai.config import AISettings
        from nakama_kun.ai.providers.openrouter_provider import OpenRouterProvider
        from nakama_kun.ai.services.chat_service import ChatService
        from nakama_kun.ai.services.planner_service import PlannerService
        from nakama_kun.memory import get_memory_repository

        ai_settings = AISettings()
        provider = OpenRouterProvider(ai_settings)
        chat_service = ChatService(provider)
        planner_service = PlannerService(chat_service)

        repo = get_memory_repository()
        pref_key = f"telegram_conv_plan_{chat_id}"
        conversation_id = None
        try:
            conversation_id = repo.get_preference(pref_key)
            if not conversation_id:
                conversation_id = repo.create_conversation(
                    f"Telegram Plan Chat {chat_id}", "telegram_plan"
                )
                repo.save_preference(pref_key, conversation_id)
            planner_service.history = repo.get_messages(conversation_id)
        except Exception as e:
            logger.warning(f"Failed to load Telegram memory: {e}")

        plan, raw_text = await planner_service.plan(goal)

        if conversation_id:
            try:
                if len(planner_service.history) >= 2:
                    repo.add_message(conversation_id, planner_service.history[-2])
                    repo.add_message(conversation_id, planner_service.history[-1])
            except Exception as e:
                logger.warning(f"Failed to save Telegram plan messages: {e}")

        reply = format_plan_as_markdown(plan) if plan is not None else raw_text

        from nakama_kun.telegram.utils import send_response_in_chunks
        await send_response_in_chunks(
            bot=context.bot,
            chat_id=chat_id,
            text=reply,
            status_message_id=status_msg.message_id,
        )
    except Exception as exc:
        logger.error(f"Error in plan logic: {exc}")
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg.message_id,
                text=f"❌ *Error*: {exc}",
                parse_mode="Markdown",
            )
        except Exception:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg.message_id,
                text=f"❌ Error: {exc}",
            )


def format_plan_as_markdown(plan: Any) -> str:
    """Format a Plan model object nicely in Telegram Markdown format."""
    lines = []
    lines.append("📋 *Planned Implementation*")
    lines.append("")
    lines.append("*Goal Summary*")
    lines.append(f"_{plan.goal_summary}_")
    lines.append("")

    if plan.targets:
        lines.append("*Target Files/Modules*")
        for target in plan.targets:
            lines.append(f"• `{target}`")
        lines.append("")

    if plan.assumptions:
        lines.append("*Assumptions*")
        for assumption in plan.assumptions:
            lines.append(f"• {assumption}")
        lines.append("")

    if plan.ordered_steps:
        lines.append("*Execution Steps*")
        for idx, step in enumerate(plan.ordered_steps, start=1):
            lines.append(f"{idx}. {step}")
        lines.append("")

    if plan.risks:
        lines.append("*Risks & Hazards*")
        for risk in plan.risks:
            lines.append(f"⚠️ {risk}")
        lines.append("")

    if plan.validation_checklist:
        lines.append("*Validation Checklist*")
        for item in plan.validation_checklist:
            lines.append(f"☐ {item}")
        lines.append("")

    return "\n".join(lines)


@authorized_only
async def agent_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /agent command."""
    if not update.effective_chat:
        return

    chat_id = update.effective_chat.id

    if not context.args:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ Usage: `/agent <task description>`",
            parse_mode="Markdown",
        )
        return

    task = " ".join(context.args)

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text="🤖 _Starting agent loop..._\n⚙️ _Running workspace tools..._",
        parse_mode="Markdown",
    )

    try:
        from nakama_kun.ai.config import AISettings
        from nakama_kun.ai.providers.openrouter_provider import OpenRouterProvider
        from nakama_kun.ai.services.chat_service import ChatService
        from nakama_kun.modes.agent_mode import AgentMode

        ai_settings = AISettings()
        provider = OpenRouterProvider(ai_settings)
        chat_service = ChatService(provider)

        from nakama_kun.safety.models import AutoApprovalProvider
        agent = AgentMode(chat_service, approval_provider=AutoApprovalProvider(approve=True))

        tool_schemas = agent._registry.all_schemas()

        final_answer = await agent._agent_loop(
            task, history=[], tool_schemas=tool_schemas
        )

        reply = final_answer or "Agent completed without a final response."

        from nakama_kun.telegram.utils import send_response_in_chunks
        await send_response_in_chunks(
            bot=context.bot,
            chat_id=chat_id,
            text=reply,
            status_message_id=status_msg.message_id,
        )
    except Exception as exc:
        logger.error(f"Error in agent logic: {exc}")
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg.message_id,
                text=f"❌ *Error*: {exc}",
                parse_mode="Markdown",
            )
        except Exception:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg.message_id,
                text=f"❌ Error: {exc}",
            )



