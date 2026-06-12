# WRITE_FILE_POSTMORTEM: `RuntimeWarning: coroutine was never awaited`

## Executive Summary
During execution of the autonomous agent loop, calling the `write_file` tool triggered a `RuntimeWarning: coroutine was never awaited`. This document traces the execution path, identifies the root cause of the warning, details the transition of the tool execution layer to an asynchronous design, and documents the verification results.

---

## 1. Traced Execution Path
The execution path for the `write_file` tool call under the agent loop starts at the orchestrator level and goes down to the approval prompting UI:

1. **`AgentMode._agent_loop()`** (async context)
   - Compiles and invokes the LangGraph workflow: `await graph.ainvoke(...)`.
2. **`executor_node`** (async context, `/src/nakama_kun/orchestration/nodes.py`)
   - Receives LLM tool calls.
   - Dispatches each tool synchronously: `result = tool_router.dispatch(name, arguments)`.
3. **`ToolRouter.dispatch()`** (sync context, `/src/nakama_kun/tools/router.py`)
   - Looks up the tool and calls it synchronously: `result = tool.execute(**parsed_args)`.
4. **`WriteFileTool.execute()`** (sync context, `/src/nakama_kun/tools/core/write_file.py`)
   - Resolves paths and prepares proposal.
   - Routes through Safety Manager synchronously: `applied = self.safety_manager.apply_proposal(...)`.
5. **`SafetyManager.apply_proposal()`** (sync context, `/src/nakama_kun/safety/manager.py`)
   - Requests user approval synchronously: `provider.request_approval(proposal)`.
6. **`TerminalApprovalProvider.request_approval()`** (sync context, `/src/nakama_kun/safety/terminal.py`)
   - Renders a panel containing the diff.
   - Calls the blocking confirm prompt: `questionary.confirm(...).ask()`.

---

## 2. Root Cause Explanation

### The conflict between synchronous prompts and running event loops
`questionary` is built on top of `prompt_toolkit` (version 3.0+), which uses `asyncio` under the hood. 

1. When calling `questionary.confirm(...).ask()` synchronously, `prompt_toolkit` attempts to run its application inside a new event loop using `asyncio.run(self.run_async())`.
2. However, because `executor_node` is already executing within an **active running asyncio event loop** (started by LangGraph's `ainvoke`), Python raises a `RuntimeError: asyncio.run() cannot be called from a running event loop`.
3. Because this error halts the execution of `asyncio.run()`, the coroutine returned by `self.run_async()` is left unawaited.
4. Python eventually garbage-collects this unawaited coroutine, raising the warning:
   ```
   sys:1: RuntimeWarning: coroutine 'Application.run_async' was never awaited
   ```

---

## 3. Implemented Fix

To eliminate this warning and establish a robust, non-blocking asynchronous workflow, the tool execution stack was transitioned to a fully asynchronous design:

1. **Async Tool Interface (`BaseTool`)**:
   Modified `BaseTool.execute` in `/src/nakama_kun/tools/interfaces.py` to be an `async def`.
2. **Core Tools Asynchrony**:
   Updated all 5 core tools (`read_file`, `write_file`, `list_files`, `search_files`, `run_command`) in `/src/nakama_kun/tools/core/` to use `async def execute()`.
3. **Async Safety Checks**:
   - Updated `ApprovalProvider.request_approval` and `AutoApprovalProvider.request_approval` to be `async def`.
   - Changed `TerminalApprovalProvider.request_approval` to use `await questionary.confirm(...).ask_async()` to correctly leverage the existing running event loop.
   - Updated `SafetyManager.apply_proposal` to be `async def` and `await provider.request_approval(proposal)`.
4. **Tool Router & Dispatching**:
   - Transitioned `ToolRouter.dispatch` to `async def` and called `result = await tool.execute(**parsed_args)`.
   - Updated the LangGraph `executor_node` to use `result = await tool_router.dispatch(name, arguments)`.
   - Updated `AgentMode._execute_tool_call` to `async def` and call `await self._router.dispatch(...)`.

---

## 4. Verification Results

### Regression Tests Added (`/tests/test_write_file_async.py`)
A comprehensive suite of async unit and integration tests was added to verify all standard file operations under the new async stack:
- **`test_write_file_create`**: Verifies that creating a new file returns `success=True`, writes the correct content, and does not trigger any `RuntimeWarning`.
- **`test_write_file_modify`**: Verifies modifying an existing file returns `success=True` and updates content.
- **`test_write_file_overwrite`**: Verifies overwriting a file succeeds and contains the correct overwritten content.
- **`test_write_file_nested_dir`**: Verifies parent directory tree is recursively created.
- **`test_write_file_terminal_approval_provider_async`**: Verifies that the asynchronous confirmation prompt works properly with the `TerminalApprovalProvider`.

### Test Execution Output
All 129 test cases in the test suite pass successfully, with zero warnings:

```
============================= test session starts ==============================
platform linux -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /home/tankaizokuo/Code/TanClaw
configfile: pyproject.toml
plugins: cov-7.1.0, anyio-4.13.0, langsmith-0.8.15
collected 129 items

...
tests/test_write_file_async.py::test_write_file_create[asyncio] PASSED   [ 96%]
tests/test_write_file_async.py::test_write_file_modify[asyncio] PASSED   [ 97%]
tests/test_write_file_async.py::test_write_file_overwrite[asyncio] PASSED [ 98%]
tests/test_write_file_async.py::test_write_file_nested_dir[asyncio] PASSED [ 99%]
tests/test_write_file_async.py::test_write_file_terminal_approval_provider_async[asyncio] PASSED [100%]
============================= 129 passed in 1.21s ==============================
```
No `RuntimeWarning: coroutine was never awaited` is triggered.
