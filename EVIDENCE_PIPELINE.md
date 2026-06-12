# Evidence Pipeline Analysis & Evidence Store Design

This document details the analysis of how evidence is collected, summarized, and potentially lost or truncated during agent execution. It also details the design of the **Evidence Store** to preserve tool outputs, file validations, test outputs, and command outputs for the quality control reviewer.

---

## Part 1: Tracing Evidence Aggregation

### 1. Trace of Evidence Collected During Execution
During execution, the `executor_node` runs the agent loop (up to 10 rounds) where the LLM calls workspace tools.
- **`tool_results` Accumulation**: Every tool call's name, arguments, success status, and raw text output are recorded in a dictionary and appended to `state["tool_results"]`. This includes `read_file`, `write_file`, `list_files`, `search_files`, and `run_command` calls.
- **Verification Layer**: After tool execution, the `verifier_node` invokes `VerificationLayer.run()`, which extracts evidence from `tool_results`:
  - It reads newly written/modified paths back from disk to construct `FileArtifact` objects.
  - It records file existence checks (`ExistenceCheck`).
  - It records command execution exit codes and output snippets (`CommandResult`).
  - It parses pytest/unittest outputs into a `test_summary`.

### 2. How Evidence is Summarized
The collected evidence is summarized in the `VerificationReport` and formatted into a text block using:
- **`VerificationReport.evaluate_outcome()`**: Analyzes artifacts, command results, and test counts to pre-classify a task outcome signal (`APPROVE` / `REJECT` / `UNCERTAIN`).
- **`VerificationReport.to_reviewer_text()`**: Renders a human-readable summary listing created files, modified files, file existence status checks, run command outputs, and the workspace snapshot.

### 3. Where Evidence is Lost, Truncated, or Overwritten
We identified several critical gaps where evidence is lost or discarded:
- **Discarded Tool-Read Content**: For `read_file`, the verification layer only records whether the file path exists on disk at the final moment of verification (via `exists = resolved.exists()`). The actual content successfully returned during the tool call is never preserved or shown to the reviewer. If the file was a temporary file that got deleted before the verifier node ran, the verifier node flags it as `❌ MISSING` and the reviewer rejects it, ignoring the successful tool read.
- **Text Truncation**: Both file content snippets and command output snippets are truncated to `max_content_chars` (defaulting to 2000 characters). While useful to prevent prompt bloat, this throws away part of the output context.
- **Overwritten/Discarded Fallback Data**: When `verification_report` is missing/None, the reviewer node falls back to a minimal json string containing only tool names and success flags, discarding all outputs.
- **Non-File/Non-Command Tools Ignored**: Any custom tools or tools other than file/command tools have their output completely ignored by the verifier node.

---

## Part 2: Evidence Store Design

To resolve these issues, we introduce the **Evidence Store** (`EvidenceStore`), which acts as a structured repository preserving all execution evidence.

### Requirements & Design
1. **Preserve Tool Outputs**: Every tool call in `tool_results` is preserved with its full raw output in `ToolOutputEvidence`.
2. **Preserve File Validations**: Captures read-time contents, write-time contents, and final physical disk checks in `FileValidationEvidence`. This ensures that even if a file is missing on disk at the end of the run, the fact that it was successfully read or written with specific content is preserved.
3. **Preserve Command Outputs**: Preserves the command string, exit code, and full raw stdout/stderr output in `CommandOutputEvidence`.
4. **Preserve Test Outputs**: Preserves parsed test counts (passed, failed, skipped, errors) in `TestOutputEvidence`.

The reviewer receives this complete historical log, allowing it to approve tasks even if intermediate files were cleaned up or final physical checks show them as missing.
