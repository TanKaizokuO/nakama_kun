import contextlib
import json
import time
from collections.abc import AsyncIterator
from typing import Any

import openai
from openai import AsyncOpenAI

from nakama_kun.ai.config import AISettings
from nakama_kun.ai.exceptions import (
    AIError,
    APIKeyNotFoundError,
    InvalidModelError,
    NetworkError,
    RateLimitError,
)
from nakama_kun.ai.models.message import Message, ToolCall
from nakama_kun.ai.models.response import AIResponse, TokenUsage
from nakama_kun.ai.providers.base_provider import BaseProvider


class OpenRouterProvider(BaseProvider):
    """OpenRouter LLM provider using the AsyncOpenAI SDK client."""

    def __init__(self, settings: AISettings) -> None:
        self.settings = settings
        self._client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        """Lazily initialize and return the AsyncOpenAI client."""
        if self._client is None:
            key = self.settings.openrouter_api_key
            if not key or not key.get_secret_value():
                raise APIKeyNotFoundError("OpenAI API key not found.")

            self._client = AsyncOpenAI(
                api_key=key.get_secret_value(),
                base_url=self.settings.openrouter_base_url,
            )
        return self._client

    def _convert_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert internal Message models to the OpenAI payload dict format."""
        payload = []
        for msg in messages:
            item: dict[str, Any] = {"role": msg.role}
            if msg.content is not None:
                item["content"] = msg.content
            if msg.name is not None:
                item["name"] = msg.name
            if msg.tool_call_id is not None:
                item["tool_call_id"] = msg.tool_call_id
            if msg.tool_calls is not None:
                item["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function["name"],
                            "arguments": (
                                json.dumps(tc.function["arguments"])
                                if isinstance(tc.function["arguments"], dict)
                                else tc.function["arguments"]
                            ),
                        },
                    }
                    for tc in msg.tool_calls
                ]
            payload.append(item)
        return payload

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
    ) -> AIResponse:
        start_time = time.perf_counter()
        try:
            api_messages = self._convert_messages(messages)
            kwargs: dict[str, Any] = {
                "model": self.settings.model,
                "messages": api_messages,
            }
            if tools:
                kwargs["tools"] = tools
            if tool_choice:
                kwargs["tool_choice"] = tool_choice

            response = await self.client.chat.completions.create(**kwargs)
            latency = time.perf_counter() - start_time

            prompt_tokens = response.usage.prompt_tokens if response.usage else 0
            completion_tokens = (
                response.usage.completion_tokens if response.usage else 0
            )
            total_tokens = response.usage.total_tokens if response.usage else 0

            # Parse tool calls if present
            internal_tool_calls = None
            choice_msg = response.choices[0].message
            if choice_msg.tool_calls:
                internal_tool_calls = []
                for tc in choice_msg.tool_calls:
                    args = tc.function.arguments
                    if isinstance(args, str):
                        with contextlib.suppress(Exception):
                            args = json.loads(args)
                    internal_tool_calls.append(
                        ToolCall(
                            id=tc.id,
                            type=tc.type,
                            function={"name": tc.function.name, "arguments": args},
                        )
                    )

            return AIResponse(
                content=choice_msg.content,
                model=response.model,
                usage=TokenUsage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                ),
                finish_reason=response.choices[0].finish_reason,
                latency=latency,
                tool_calls=internal_tool_calls,
            )
        except openai.AuthenticationError as e:
            raise APIKeyNotFoundError("OpenAI API key not found.") from e
        except openai.RateLimitError as e:
            raise RateLimitError("Rate limit exceeded. Try again later.") from e
        except openai.APIConnectionError as e:
            raise NetworkError("Unable to reach provider.") from e
        except openai.NotFoundError as e:
            raise InvalidModelError("Configured model unavailable.") from e
        except openai.APIStatusError as e:
            raise AIError(f"OpenRouter API status error: {e.message}") from e
        except Exception as e:
            raise AIError(f"Unexpected OpenRouter error: {str(e)}") from e

    async def generate_stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
    ) -> AsyncIterator[str]:
        try:
            api_messages = self._convert_messages(messages)
            kwargs: dict[str, Any] = {
                "model": self.settings.model,
                "messages": api_messages,
                "stream": True,
            }
            if tools:
                kwargs["tools"] = tools
            if tool_choice:
                kwargs["tool_choice"] = tool_choice

            stream = await self.client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except openai.AuthenticationError as e:
            raise APIKeyNotFoundError("OpenAI API key not found.") from e
        except openai.RateLimitError as e:
            raise RateLimitError("Rate limit exceeded. Try again later.") from e
        except openai.APIConnectionError as e:
            raise NetworkError("Unable to reach provider.") from e
        except openai.NotFoundError as e:
            raise InvalidModelError("Configured model unavailable.") from e
        except openai.APIStatusError as e:
            raise AIError(f"OpenRouter API status error: {e.message}") from e
        except Exception as e:
            raise AIError(f"Unexpected OpenRouter error: {str(e)}") from e

    async def verify_connectivity(self) -> bool:
        try:
            await self.client.chat.completions.create(
                model=self.settings.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            return True
        except openai.AuthenticationError as e:
            raise APIKeyNotFoundError("OpenAI API key not found.") from e
        except openai.RateLimitError as e:
            raise RateLimitError("Rate limit exceeded. Try again later.") from e
        except openai.APIConnectionError as e:
            raise NetworkError("Unable to reach provider.") from e
        except openai.NotFoundError as e:
            raise InvalidModelError("Configured model unavailable.") from e
        except Exception as e:
            raise AIError(f"Connection verification failed: {e}") from e
