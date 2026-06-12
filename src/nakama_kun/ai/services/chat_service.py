import time
from collections.abc import AsyncIterator
from typing import Any

from loguru import logger

from nakama_kun.ai.interfaces import LLMProvider
from nakama_kun.ai.models.message import Message
from nakama_kun.ai.models.response import AIResponse
from nakama_kun.ai.prompts.system_prompt import DEFAULT_SYSTEM_PROMPT


class ChatService:
    """High-level orchestration service for conversation handling and logging."""

    def __init__(
        self, provider: LLMProvider, system_prompt: str = DEFAULT_SYSTEM_PROMPT
    ) -> None:
        self.provider = provider
        self.system_prompt = system_prompt
        self.history: list[Message] = []

    def get_messages(self, prompt: str) -> list[Message]:
        """Combine default system prompt, chat history, and new user prompt."""
        messages = [Message(role="system", content=self.system_prompt)]
        messages.extend(self.history)
        messages.append(Message(role="user", content=prompt))
        return messages

    async def chat(self, prompt: str) -> AIResponse:
        """Send a standard prompt to the provider and return a full AIResponse.

        Saves user and assistant messages in chat history and logs metadata.
        """
        messages = self.get_messages(prompt)
        logger.info(f"Chat request starting. Messages count: {len(messages)}")

        try:
            response = await self.provider.generate(messages)

            # Save user prompt and generated response to history
            self.history.append(Message(role="user", content=prompt))
            self.history.append(
                Message(role="assistant", content=response.content or "")
            )

            logger.info(
                f"Chat request successful. Model: {response.model} | "
                f"Latency: {response.latency:.2f}s | "
                f"Tokens: {response.usage.total_tokens} (Prompt: {response.usage.prompt_tokens}, Completion: {response.usage.completion_tokens})"
            )
            return response
        except Exception as e:
            logger.error(f"Chat request failed: {e}")
            raise

    async def chat_stream(self, prompt: str) -> AsyncIterator[str]:
        """Stream response tokens from the provider.

        Saves user and assistant messages in chat history after stream completion
        and logs performance statistics.
        """
        messages = self.get_messages(prompt)
        logger.info(f"Chat stream request starting. Messages count: {len(messages)}")

        start_time = time.perf_counter()
        full_content = []

        try:
            async for token in self.provider.generate_stream(messages):
                full_content.append(token)
                yield token

            latency = time.perf_counter() - start_time
            content_str = "".join(full_content)

            # Save user prompt and generated response to history
            self.history.append(Message(role="user", content=prompt))
            self.history.append(Message(role="assistant", content=content_str))

            logger.info(
                f"Chat stream request completed. "
                f"Latency: {latency:.2f}s | Chars: {len(content_str)}"
            )
        except Exception as e:
            logger.error(f"Chat stream request failed: {e}")
            raise

    async def chat_with_tools(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
    ) -> AIResponse:
        """Send an existing message list plus tool schemas to the provider.

        Unlike ``chat`` this method does NOT modify ``self.history`` — the
        caller (Agent Mode loop) manages the message list directly so it can
        append tool results between rounds.

        Args:
            messages: The full message history for this round (including system
                prompt, previous user/assistant turns, and tool results).
            tools: OpenAI-compatible tool schema list from ``ToolRegistry.all_schemas()``.

        Returns:
            The raw :class:`~nakama_kun.ai.models.response.AIResponse`, which
            may have ``finish_reason == "tool_calls"`` and a non-empty
            ``tool_calls`` list.
        """
        logger.info(
            f"Agent tool-capable request. Messages: {len(messages)}, "
            f"Tools: {len(tools)}"
        )
        try:
            response = await self.provider.generate(
                messages, tools=tools, tool_choice="auto"
            )
            logger.info(
                f"Agent response received. finish_reason={response.finish_reason} | "
                f"tool_calls={len(response.tool_calls or [])}"
            )
            return response
        except Exception as e:
            logger.error(f"Agent tool-capable request failed: {e}")
            raise

    async def verify_connectivity(self) -> bool:
        """Verify LLM connectivity using the provider's check."""
        logger.info("Verifying AI provider connectivity...")
        try:
            res = await self.provider.verify_connectivity()
            logger.info("AI provider connectivity verification successful.")
            return res
        except Exception as e:
            logger.error(f"AI provider connectivity verification failed: {e}")
            raise

