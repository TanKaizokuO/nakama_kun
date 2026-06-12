import json
import pytest
from nakama_kun.tools.core.run_command import RunCommandTool
from nakama_kun.orchestration.verification import VerificationLayer, VerificationReport
from nakama_kun.orchestration.state import AgentState


@pytest.mark.anyio
async def test_run_command_success_json(tmp_path: object) -> None:
    tool = RunCommandTool(cwd=str(tmp_path))
    result = await tool.execute(cmd="echo 'hello world'")
    assert result.success

    # Parse output as JSON
    data = json.loads(result.output)
    assert data["success"] is True
    assert data["exit_code"] == 0
    assert "hello world" in data["stdout"]
    assert data["stderr"] == ""


@pytest.mark.anyio
async def test_run_command_failing_json(tmp_path: object) -> None:
    tool = RunCommandTool(cwd=str(tmp_path))
    result = await tool.execute(cmd="echo 'error msg' >&2 && exit 42")
    assert not result.success

    # Parse error as JSON
    data = json.loads(result.error)
    assert data["success"] is False
    assert data["exit_code"] == 42
    assert data["stdout"] == ""
    assert "error msg" in data["stderr"]


@pytest.mark.anyio
async def test_run_command_chained_json(tmp_path: object) -> None:
    tool = RunCommandTool(cwd=str(tmp_path))
    result = await tool.execute(cmd="echo 'first' && echo 'second' >&2 && exit 5")
    assert not result.success

    data = json.loads(result.output)
    assert data["success"] is False
    assert data["exit_code"] == 5
    assert "first" in data["stdout"]
    assert "second" in data["stderr"]


def test_verification_layer_parses_json() -> None:
    layer = VerificationLayer()

    # Successful command JSON content
    success_json = json.dumps({
        "success": True,
        "exit_code": 0,
        "stdout": "tests passed successfully",
        "stderr": ""
    })

    # Failing command JSON content (with ERROR: prefix)
    fail_json = "ERROR: " + json.dumps({
        "success": False,
        "exit_code": 1,
        "stdout": "1 passed, 1 failed",
        "stderr": "warning: deprecation"
    })

    state: AgentState = {
        "goal": "Run tests",
        "plan": None,
        "messages": [],
        "tool_results": [
            {
                "tool": "run_command",
                "arguments": {"cmd": "pytest -v"},
                "success": True,
                "content": success_json,
            },
            {
                "tool": "run_command",
                "arguments": {"cmd": "pytest -v --fail"},
                "success": False,
                "content": fail_json,
            }
        ],
        "verification_report": None,
        "reviewer_feedback": None,
        "retry_count": 0,
        "final_response": None,
        "status": "reviewing",
    }

    report = layer.run(state)
    assert isinstance(report, VerificationReport)
    assert len(report.command_results) == 2

    # Verify first command result parsing
    cr1 = report.command_results[0]
    assert cr1.cmd == "pytest -v"
    assert cr1.exit_code == 0
    assert cr1.success is True
    assert "tests passed successfully" in cr1.stdout_snippet

    # Verify second command result parsing
    cr2 = report.command_results[1]
    assert cr2.cmd == "pytest -v --fail"
    assert cr2.exit_code == 1
    assert cr2.success is False  # Derived from exit_code or test parser
    assert "1 passed, 1 failed" in cr2.stdout_snippet
    assert "warning: deprecation" in cr2.stdout_snippet
