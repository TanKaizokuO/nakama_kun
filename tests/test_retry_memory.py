from unittest.mock import AsyncMock, MagicMock

import pytest

from nakama_kun.ai.models.plan import Plan
from nakama_kun.ai.services.planner_service import PlannerService
from nakama_kun.orchestration.nodes import make_planner_node
from nakama_kun.orchestration.state import AgentState
from nakama_kun.orchestration.verification import (
    CommandResult,
    ExistenceCheck,
    FileArtifact,
    VerificationReport,
)


@pytest.mark.anyio
async def test_planner_node_retry_memory() -> None:
    # 1. Mock PlannerService
    mock_planner_service = MagicMock(spec=PlannerService)
    mock_plan = Plan(
        goal_summary="Summary of goal",
        targets=["test.py"],
        assumptions=[],
        ordered_steps=["Step 1"],
        risks=[],
        validation_checklist=[],
    )
    mock_planner_service.plan = AsyncMock(return_value=(mock_plan, "Plan raw details"))

    planner_node = make_planner_node(mock_planner_service)

    # --- ATTEMPT 1: Initial planning ---
    state_attempt_1: AgentState = {
        "goal": "Write a python file and run tests",
        "plan": None,
        "messages": [],
        "tool_results": [],
        "verification_report": None,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "planning",
    }

    result_1 = await planner_node(state_attempt_1)
    assert result_1["plan"] == mock_plan
    assert result_1["status"] == "executing"
    assert result_1["retry_count"] == 0

    # Verify that plan prompt was simply the goal
    mock_planner_service.plan.assert_called_with("Write a python file and run tests")
    mock_planner_service.plan.reset_mock()

    # --- ATTEMPT 2: Replanning with retry memory ---
    # Construct a mock verification report
    mock_report = VerificationReport(
        files_created=[
            FileArtifact(path="result.py", exists=False, content_snippet="", size_bytes=0)
        ],
        files_modified=[],
        existence_checks=[
            ExistenceCheck(path="test_result.py", exists=False)
        ],
        command_results=[
            CommandResult(
                cmd="pytest",
                exit_code=1,
                stdout_snippet="Failed: assert 1 == 2",
                success=False,
                test_summary={
                    "passed": 2,
                    "failed": 1,
                    "errors": 0,
                    "skipped": 0,
                    "success": False,
                }
            )
        ],
        workspace_snapshot=[],
        summary="Verification failed."
    )

    state_attempt_2: AgentState = {
        "goal": "Write a python file and run tests",
        "plan": mock_plan,
        "messages": [],
        "tool_results": [
            {
                "tool": "write_file",
                "arguments": {"path": "result.py", "content": "x = 42"},
                "success": True,
                "content": "Successfully wrote 6 characters.",
            },
            {
                "tool": "run_command",
                "arguments": {"cmd": "pytest"},
                "success": False,
                "content": "Exit code: 1\nFailed: assert 1 == 2",
            }
        ],
        "verification_report": mock_report,
        "reviewer_feedback": "[REJECTED] Test failed.",
        "retry_count": 0,
        "final_response": None,
        "status": "planning",
    }

    result_2 = await planner_node(state_attempt_2)
    assert result_2["plan"] == mock_plan
    assert result_2["status"] == "executing"
    assert result_2["retry_count"] == 1  # Incremented from 0 to 1

    # Verify that the mock planner service was called with the enriched prompt
    called_prompt = mock_planner_service.plan.call_args[0][0]

    # Assert that Attempt 2 prompt differs from Attempt 1 prompt
    assert called_prompt != "Write a python file and run tests"

    # Assert specific sections are present
    assert "### Reviewer Feedback" in called_prompt
    assert "[REJECTED] Test failed." in called_prompt

    assert "### Completed Actions" in called_prompt
    assert "write_file" in called_prompt
    assert '"path": "result.py"' in called_prompt

    assert "### Previous Failures" in called_prompt
    assert "run_command" in called_prompt
    assert '"cmd": "pytest"' in called_prompt
    assert "Exit code: 1" in called_prompt

    assert "### Failed Validations" in called_prompt
    assert "Expected file artifact does not exist: result.py" in called_prompt
    assert "Referenced file does not exist: test_result.py" in called_prompt
    assert "Test runner command failed: 'pytest'" in called_prompt
    assert "Tests: 2 passed, 1 failed, 0 errors, 0 skipped" in called_prompt


@pytest.mark.anyio
async def test_planner_node_retry_memory_no_verification_report() -> None:
    # 1. Mock PlannerService
    mock_planner_service = MagicMock(spec=PlannerService)
    mock_plan = Plan(
        goal_summary="Summary of goal",
        targets=["test.py"],
        assumptions=[],
        ordered_steps=["Step 1"],
        risks=[],
        validation_checklist=[],
    )
    mock_planner_service.plan = AsyncMock(return_value=(mock_plan, "Plan raw details"))

    planner_node = make_planner_node(mock_planner_service)

    state: AgentState = {
        "goal": "Write a python file and run tests",
        "plan": mock_plan,
        "messages": [],
        "tool_results": [
            {
                "tool": "write_file",
                "arguments": {"path": "result.py", "content": "x = 42"},
                "success": True,
                "content": "Successfully wrote 6 characters.",
            }
        ],
        "verification_report": None,  # No verification report
        "reviewer_feedback": "[REJECTED] Test failed.",
        "retry_count": 1,
        "final_response": None,
        "status": "planning",
    }

    result = await planner_node(state)
    assert result["retry_count"] == 2

    # Verify that prompt was enriched but didn't crash
    called_prompt = mock_planner_service.plan.call_args[0][0]
    assert "### Reviewer Feedback" in called_prompt
    assert "### Failed Validations" in called_prompt
    # Since report is None, failed validations should format as "(none)"
    assert "### Failed Validations\n(none)" in called_prompt

