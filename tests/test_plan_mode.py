from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nakama_kun.ai.models.plan import Plan, parse_plan
from nakama_kun.ai.models.response import AIResponse, TokenUsage
from nakama_kun.ai.prompts.system_prompt import PLANNER_SYSTEM_PROMPT
from nakama_kun.ai.services.planner_service import PlannerService
from nakama_kun.core.constants import NavSignal
from nakama_kun.modes.plan_mode import PlanMode


def _make_ai_response(content: str) -> AIResponse:
    return AIResponse(
        content=content,
        model="test-model",
        usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        finish_reason="stop",
        latency=0.1,
    )


class TestPlanParsing:
    """Tests the parsing of structured plans from LLM responses."""

    def test_parse_valid_json_direct(self) -> None:
        raw_json = (
            '{\n'
            '  "goal_summary": "Summary of goal",\n'
            '  "assumptions": ["Assumption 1"],\n'
            '  "ordered_steps": ["Step 1", "Step 2"],\n'
            '  "risks": ["Risk 1"],\n'
            '  "validation_checklist": ["Check 1"],\n'
            '  "targets": ["Target 1"]\n'
            '}'
        )
        plan = parse_plan(raw_json)
        assert plan is not None
        assert plan.goal_summary == "Summary of goal"
        assert plan.assumptions == ["Assumption 1"]
        assert plan.ordered_steps == ["Step 1", "Step 2"]
        assert plan.risks == ["Risk 1"]
        assert plan.validation_checklist == ["Check 1"]
        assert plan.targets == ["Target 1"]

    def test_parse_json_markdown_block(self) -> None:
        raw_markdown = (
            "Here is the plan:\n\n"
            "```json\n"
            "{\n"
            '  "goal_summary": "Markdown goal",\n'
            '  "assumptions": [],\n'
            '  "ordered_steps": ["Step A"],\n'
            '  "risks": [],\n'
            '  "validation_checklist": [],\n'
            '  "targets": []\n'
            "}\n"
            "```\n"
            "Hope this helps!"
        )
        plan = parse_plan(raw_markdown)
        assert plan is not None
        assert plan.goal_summary == "Markdown goal"
        assert plan.ordered_steps == ["Step A"]

    def test_parse_general_markdown_block(self) -> None:
        raw_markdown = (
            "```\n"
            "{\n"
            '  "goal_summary": "General block goal",\n'
            '  "assumptions": [],\n'
            '  "ordered_steps": ["Step B"],\n'
            '  "risks": [],\n'
            '  "validation_checklist": [],\n'
            '  "targets": []\n'
            "}\n"
            "```"
        )
        plan = parse_plan(raw_markdown)
        assert plan is not None
        assert plan.goal_summary == "General block goal"
        assert plan.ordered_steps == ["Step B"]

    def test_parse_invalid_json_returns_none(self) -> None:
        raw_invalid = "{invalid json"
        plan = parse_plan(raw_invalid)
        assert plan is None


class TestPlannerService:
    """Tests the PlannerService logic and history maintenance."""

    @pytest.mark.anyio
    async def test_planner_service_calls_provider_and_maintains_history(self) -> None:
        chat_service = MagicMock()
        chat_service.provider = MagicMock()
        chat_service.provider.settings = MagicMock()
        chat_service.provider.settings.openrouter_model = "test-model"

        # Mock LLM response representing structured plan
        raw_plan = (
            '{\n'
            '  "goal_summary": "Mock summary",\n'
            '  "assumptions": [],\n'
            '  "ordered_steps": ["Step 1"],\n'
            '  "risks": [],\n'
            '  "validation_checklist": [],\n'
            '  "targets": []\n'
            '}'
        )
        chat_service.provider.generate = AsyncMock(return_value=_make_ai_response(raw_plan))

        service = PlannerService(chat_service)
        assert len(service.history) == 0

        plan, raw_text = await service.plan("Test query")

        assert plan is not None
        assert plan.goal_summary == "Mock summary"
        assert raw_text == raw_plan

        # Verify chat history was saved correctly
        assert len(service.history) == 2
        assert service.history[0].role == "user"
        assert service.history[0].content == "Test query"
        assert service.history[1].role == "assistant"
        assert service.history[1].content == raw_plan

        # Verify that the system prompt was sent to the provider call
        called_messages = chat_service.provider.generate.call_args[0][0]
        assert called_messages[0].role == "system"
        assert called_messages[0].content.startswith(PLANNER_SYSTEM_PROMPT)
        assert called_messages[1].role == "user"
        assert called_messages[1].content == "Test query"


class TestPlanMode:
    """Tests the PlanMode REPL loop, rendering, and navigation."""

    def _make_chat_service(self, responses: list[AIResponse]) -> Any:
        chat_service = MagicMock()
        chat_service.provider = MagicMock()
        chat_service.provider.settings = MagicMock()
        chat_service.provider.settings.openrouter_model = "test-model"
        chat_service.provider.generate = AsyncMock(side_effect=responses)
        return chat_service

    @patch("questionary.text")
    def test_run_navigation_back(self, mock_text: MagicMock) -> None:
        """Typing 'back' breaks the loop and returns NavSignal.BACK."""
        chat_service = self._make_chat_service([])
        plan_mode = PlanMode(chat_service)

        # Mock user entering 'back' immediately
        mock_input = MagicMock()
        mock_input.ask_async = AsyncMock(return_value="back")
        mock_text.return_value = mock_input

        signal = plan_mode.run()
        assert signal == NavSignal.BACK
        mock_text.assert_called_once()
        chat_service.provider.generate.assert_not_called()

    @patch("questionary.text")
    def test_run_navigation_exit(self, mock_text: MagicMock) -> None:
        """Typing 'exit' breaks the loop and returns NavSignal.BACK."""
        chat_service = self._make_chat_service([])
        plan_mode = PlanMode(chat_service)

        # Mock user entering 'exit' immediately
        mock_input = MagicMock()
        mock_input.ask_async = AsyncMock(return_value="exit")
        mock_text.return_value = mock_input

        signal = plan_mode.run()
        assert signal == NavSignal.BACK
        mock_text.assert_called_once()
        chat_service.provider.generate.assert_not_called()

    @patch("questionary.text")
    def test_run_ctrl_c(self, mock_text: MagicMock) -> None:
        """Pressing Ctrl-C raises KeyboardInterrupt and returns NavSignal.BACK."""
        chat_service = self._make_chat_service([])
        plan_mode = PlanMode(chat_service)

        mock_input = MagicMock()
        mock_input.ask_async = AsyncMock(side_effect=KeyboardInterrupt)
        mock_text.return_value = mock_input

        signal = plan_mode.run()
        assert signal == NavSignal.BACK

    @patch("questionary.text")
    def test_run_renders_structured_plan(self, mock_text: MagicMock) -> None:
        """PlanMode successfully queries LLM, parses structure, and renders it."""
        raw_plan = (
            '{\n'
            '  "goal_summary": "Structured summary",\n'
            '  "assumptions": ["A1"],\n'
            '  "ordered_steps": ["S1"],\n'
            '  "risks": ["R1"],\n'
            '  "validation_checklist": ["V1"],\n'
            '  "targets": ["T1"]\n'
            '}'
        )
        chat_service = self._make_chat_service([_make_ai_response(raw_plan)])
        plan_mode = PlanMode(chat_service)

        # Mock user enters a query, then 'back'
        mock_input_query = MagicMock()
        mock_input_query.ask_async = AsyncMock(return_value="Create website")
        mock_input_back = MagicMock()
        mock_input_back.ask_async = AsyncMock(return_value="back")
        mock_text.side_effect = [mock_input_query, mock_input_back]

        with patch.object(plan_mode, "_render_plan") as mock_render:
            signal = plan_mode.run()
            assert signal == NavSignal.BACK
            mock_render.assert_called_once()
            plan_arg = mock_render.call_args[0][0]
            assert isinstance(plan_arg, Plan)
            assert plan_arg.goal_summary == "Structured summary"

    @patch("questionary.text")
    def test_run_renders_unstructured_plan(self, mock_text: MagicMock) -> None:
        """PlanMode falls back to rendering unstructured markdown if JSON parsing fails."""
        raw_text = "This is a simple plain text plan without JSON."
        chat_service = self._make_chat_service([_make_ai_response(raw_text)])
        plan_mode = PlanMode(chat_service)

        # Mock user enters query, then 'back'
        mock_input_query = MagicMock()
        mock_input_query.ask_async = AsyncMock(return_value="Tell me a plan")
        mock_input_back = MagicMock()
        mock_input_back.ask_async = AsyncMock(return_value="back")
        mock_text.side_effect = [mock_input_query, mock_input_back]

        with patch.object(plan_mode, "_render_unstructured") as mock_render:
            signal = plan_mode.run()
            assert signal == NavSignal.BACK
            mock_render.assert_called_once_with(raw_text)

    def test_system_prompt_forbids_tools_and_writes(self) -> None:
        """Verifies that the PLANNER_SYSTEM_PROMPT contains direct negative constraints."""
        assert "FORBIDDEN" in PLANNER_SYSTEM_PROMPT
        assert "tools" in PLANNER_SYSTEM_PROMPT.lower()
        assert "modify" in PLANNER_SYSTEM_PROMPT.lower()
        assert "file" in PLANNER_SYSTEM_PROMPT.lower()
