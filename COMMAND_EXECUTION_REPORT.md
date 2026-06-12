# Command Execution Semantics Audit Report

This report documents our audit of the `run_command` tool in `nakama_kun`, analyzing how execution outcomes, exit codes, and output streams are handled, and details the implementation of consistent semantics using a structured JSON output.

---

## Part 1: Audit & Findings

### 1. Analysis of Current Implementation
The `RunCommandTool` executes commands using Python's `subprocess.run(..., shell=True, capture_output=True, text=True)`.
- `capture_output=True` redirects standard output and error streams separately into `result.stdout` and `result.stderr`.
- `shell=True` passes the command string directly to the shell (`/bin/sh` on Unix/Linux), allowing chained commands and shell utilities to run.

### 2. Success/Failure Determination Gaps
Previously, `RunCommandTool` determined success simply by checking if `returncode == 0`:
```python
success = result.returncode == 0
if success:
    return ToolResult(success=True, output=output)
return ToolResult(success=False, output=output, error=error_message)
```
When `ToolResult.success` is `False`, the orchestration layer's router and executor processed it as:
```python
content = f"ERROR: {result.error}"
```
This discarded the actual `stdout` and `stderr` content completely! Consequently, if a test runner command exited with code 1 (indicating some tests failed), the LLM/Reviewer only saw a generic "ERROR: Command exited with code 1" instead of the test failure report in the stdout.

### 3. Handling of Output Channels & Chained Commands
- **Non-zero exit codes**: Correctly captured from `result.returncode`. However, returning `success=False` on the `ToolResult` level hid the stdout.
- **Stderr output**: Capturing standard error is done separately, but combined with stdout in the old string format.
- **Mixed stdout/stderr**: Captured in separate variables but merged into a single `combined` string.
- **Chained shell commands**: Works correctly through `shell=True`, but if an intermediate command in a chain fails, the shell returns the exit code of the final command in the chain unless standard shell options like `set -e` are used.

---

## Part 2: Consistent JSON Semantics

To resolve the loss of stdout/stderr on exit code failures, `RunCommandTool` now returns a structured JSON payload for both successful and failing commands:

```json
{
  "success": true,
  "exit_code": 0,
  "stdout": "...",
  "stderr": "..."
}
```

### Key Semantics
1. **Command Execution Status**: `"success"` inside the JSON payload is `True` if `exit_code == 0`, and `False` otherwise.
2. **Tool Result Level**: `ToolResult.success` continues to reflect command success (`exit_code == 0`) for compatibility, but both `output` and `error` parameters are populated with the JSON string, ensuring standard output and standard error are never discarded.
3. **Verification Layer**: Updated to dynamically detect and parse this JSON format, extracting `stdout` and `stderr` cleanly to pass to test parsers.

---

## Part 3: Verification & Test Results

The new consistent command semantics have been validated using unit and integration tests:
- **Test Suite**: [test_run_command_semantics.py](file:///home/tankaizokuo/Code/TanClaw/tests/test_run_command_semantics.py)
  - `test_run_command_success_json`: Verifies successful commands return correct JSON with exit code 0, success=True, and stdout.
  - `test_run_command_failing_json`: Verifies failing commands return correct JSON with the non-zero exit code, success=False, and stderr.
  - `test_run_command_chained_json`: Verifies chained commands correctly propagate final exit codes and mixed stdout/stderr.
  - `test_verification_layer_parses_json`: Confirms the `VerificationLayer` successfully detects, parses, and extracts `stdout` and `stderr` from the JSON command outputs.
  - `test_run_command_truncation`: Verifies output truncation when standard output/error exceeds limits.
  - `test_run_command_mixed_outputs`: Verifies concurrent standard output and standard error stream capture.

All **167 tests** run and pass successfully in the workspace:
```bash
$ uv run pytest
============================= 167 passed in 1.33s ==============================
```
