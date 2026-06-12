# Final Report Grounding Validation Report

This report documents our audit of the final response node in `nakama_kun`, tracing the data sources used to compile final reports, and details the design to enforce strict grounding using actual verification metrics.

---

## Part 1: Audit & Findings

### 1. Tracing Data Sources of Final Response Node
We inspected the `make_final_response_node` implementation (defined in [nodes.py](file:///home/tankaizokuo/Code/TanClaw/src/nakama_kun/orchestration/nodes.py)):
- The node constructed a summary prompt utilizing only the original `goal`, proposed `plan.goal_summary`, and the number of tool execution steps (`len(tool_results)`).
- It did **not** include the list of files created or modified, test runner results, or the workspace file listings.

### 2. Gaps and LLM Memory Dependency
Because the final response node passed virtually no metrics to the LLM:
- **LLM Memory Dependency**: The final reports relied entirely on the LLM's planning memory (assumptions and steps proposed in the plan) and tool descriptions.
- **Hallucinated Outcomes**: If the plan proposed writing a file `main.py` and running `pytest`, but `main.py` was actually written to `calc.py` (via fallback tools) and no tests were run, the final report would still incorrectly assert that `main.py` was successfully written and all tests passed.
- **Incorrect Test & File Counts**: The LLM made up arbitrary test and file counts (e.g. "Verified 5 files and 12 passing tests") to produce a pleasant-sounding response.

---

## Part 2: Enforcing Grounded Metrics

To eliminate hallucinations, the final report prompt is updated to enforce strict grounding:
- **Verification Results**: Real files created and modified that exist on disk are extracted from `VerificationReport`.
- **Test Results**: Summed counts of passed, failed, errors, and skipped tests are aggregated from command results.
- **Workspace Snapshot**: The final list of active workspace files is included.

### JSON & Structured Metadata Prompt Layout
The summary prompt now includes a `### STRUCTURED METRICS` section:

```markdown
### STRUCTURED METRICS
- Total Tool Executions: {tool_count} runs
- Files Created: {files_created_list}
- Files Modified: {files_modified_list}
- Test Execution Summary: {test_summary}
- Workspace Snapshot: {workspace_snapshot}
```

The prompt instructs the LLM that it must **only** cite the values in this metadata block, and forbids it from inferring or inventing other values.
