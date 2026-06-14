from __future__ import annotations

import json
from typing import Any
from loguru import logger

from nakama_kun.agents.base import BaseAgent
from nakama_kun.agents.models import TestExecutionReport, parse_test_report
from nakama_kun.ai.models.message import Message
from nakama_kun.tools import ToolRegistry, ToolRouter


class TestAgent(BaseAgent):
    """Test Agent is responsible for test creation, execution, coverage checking, and repair loops."""

    def __init__(
        self,
        chat_service: Any,
        tool_registry: ToolRegistry,
        tool_router: ToolRouter,
    ) -> None:
        from nakama_kun.agents.prompts import TEST_AGENT_PROMPT
        super().__init__(
            name="TestAgent",
            role="tester",
            system_prompt=TEST_AGENT_PROMPT,
            chat_service=chat_service,
            tools=tool_registry.all_schemas() if tool_registry else [],
        )
        self.tool_registry = tool_registry
        self.tool_router = tool_router

    async def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        logger.info("[TestAgent] Starting testing and validation loop...")
        goal = state["goal"]

        # Formulate system prompt with context of created artifacts
        created_artifacts = state.get("created_artifacts") or []
        system_prompt = (
            f"{self.system_prompt}\n\n"
            f"### Implementation Goal\n{goal}\n\n"
            f"### Created/Modified Artifacts to Validate:\n"
            + "\n".join(f"- {a}" for a in created_artifacts)
        )

        tool_schemas = self.tool_registry.all_schemas()

        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=f"Create/run tests and verify coverage for: {', '.join(created_artifacts)}"),
            *state.get("messages", []),
        ]

        max_rounds = 5
        new_messages: list[Message] = []
        new_tool_results: list[dict[str, Any]] = []

        round_idx = 1
        for round_idx in range(1, max_rounds + 1):
            logger.info(f"[TestAgent] Test Round {round_idx}/{max_rounds}...")
            current_messages = messages + new_messages

            try:
                response = await self.chat_service.chat_with_tools(
                    current_messages, tool_schemas
                )
            except Exception as e:
                logger.warning(f"[TestAgent] Chat call failed: {e}")
                break

            if response.finish_reason == "stop" or not response.tool_calls:
                new_messages.append(Message(role="assistant", content=response.content or ""))
                logger.info("[TestAgent] Execution loop stopped by LLM.")
                break

            # Add assistant message with tool calls
            new_messages.append(
                Message(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )

            # Process tool calls
            for tc in response.tool_calls:
                name = tc.function.get("name", "")
                arguments = tc.function.get("arguments", {})

                logger.info(f"[TestAgent] Dispatching tool {name} with args: {arguments}")
                try:
                    tool_res = await self.tool_router.dispatch(name, arguments)
                    success = tool_res.success
                    content = tool_res.to_content()
                    error = tool_res.error
                except Exception as exc:
                    success = False
                    content = f"ERROR: Tool execution failed with exception: {exc}"
                    error = str(exc)

                new_tool_results.append({
                    "tool": name,
                    "arguments": arguments,
                    "success": success,
                    "content": content,
                    "error": error,
                })

                new_messages.append(
                    Message(
                        role="tool",
                        content=content,
                        tool_call_id=tc.id,
                        name=name,
                    )
                )

        # After tool execution, compile structured report via LLM
        final_prompt = (
            "Tests execution rounds complete. Summarize all test results (passed, failed, skipped, errors) "
            "and suggest recommendations in JSON format conforming to the TestExecutionReport schema."
        )

        try:
            summary_msgs = messages + new_messages + [Message(role="user", content=final_prompt)]
            response = await self.chat_service.provider.generate(summary_msgs)
            raw_text = response.content or ""
            report = parse_test_report(raw_text)
        except Exception as e:
            logger.warning(f"[TestAgent] Failed to synthesize TestExecutionReport: {e}")
            report = None

        if not report:
            logger.warning("[TestAgent] Falling back to default empty TestExecutionReport.")
            report = TestExecutionReport(
                passed=0,
                failed=0,
                skipped=0,
                errors=0,
                recommendations=["Automatic execution complete. Check verification report for details."],
            )

        history_entry = {
            "agent": self.name,
            "thought": f"Ran test agent loop. Results: {report.passed} passed, {report.failed} failed.",
            "handoff": report.model_dump(),
        }

        # Conforming to contract: return structured outputs only
        return {
            "test_report": report,
            "failure_analysis": f"Tests outcome: passed={report.passed}, failed={report.failed}, errors={report.errors}",
            "agent_history": [history_entry],
            "messages": new_messages + [
                Message(role="assistant", content=f"TestAgent validation completed. Results: passed={report.passed}, failed={report.failed}, errors={report.errors}")
            ],
            # Merge new tool results back into the central state
            "tool_results": new_tool_results,
            "status": "reviewing",
        }
