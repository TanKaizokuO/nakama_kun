# Nakama-kun Security and Safety Framework

Nakama-kun operates with strong guardrails designed to protect the host filesystem and environment. Every safety check detailed below is actively enforced in code.

---

## 1. Directory and Path Escape Containment

The primary boundary check is `assert_within_workspace` (defined in [safety.py](file:///home/tankaizokuo/Code/Nakama-Kun/src/nakama_kun/tools/safety.py) or imported by tools):

- **Mechanism**: Resolves both the workspace root and the target file path using absolute, symlink-free representation (`Path.resolve()`).
- **Enforcement**: It checks if the target path is a sub-path of the workspace root:
  ```python
  resolved_path.relative_to(resolved_root)
  ```
- **Error Condition**: If the file path resolves outside the workspace, it raises a `PathEscapeError` and blocks tool dispatch.

---

## 2. Interactive File Modification Controls

All file modifications (creations, edits, deletions) proposed by the agent route through [SafetyManager](file:///home/tankaizokuo/Code/Nakama-Kun/src/nakama_kun/safety/manager.py):

1. **Proposal Generation**: The manager reads original contents, accepts proposed changes, and generates a **Unified Diff** using `difflib.unified_diff`.
2. **Human-in-the-Loop Approval**:
   - **CLI Mode**: [TerminalApprovalProvider](file:///home/tankaizokuo/Code/Nakama-Kun/src/nakama_kun/safety/terminal.py) renders the unified diff using Rich `Syntax` syntax highlighting, and prompts the user using `questionary.confirm()`.
   - **Web UI Mode**: [WebApprovalProvider](file:///home/tankaizokuo/Code/Nakama-Kun/src/nakama_kun/web/service_wiring.py) publishes the diff to all connected WebSockets and halts execution using `asyncio.Event.wait()`. The background thread is unblocked only when the operator triggers the `/api/approvals/{id}/approve` endpoint.
3. **Rollback Logging**: The `SafetyManager` keeps a history stack (`self.history`). If a validation failure is encountered, the supervisor or operator can execute `rollback_last()` or `rollback_all()`, which deletes created files and restores modified files to their original states.

---

## 3. Command Execution Safety

Shell commands executed via `run_command` are scrutinized:

- **Banned Command Patterns**: The router blocks any shell command that matches mutating/destructive operations during **RETRIEVAL** tasks:
  - **Installers**: `pip install`, `npm install`, `yarn add`, `pnpm add`, `cargo install`, `apt-get install`, etc.
  - **Git Operations**: `git add`, `git commit`, `git push`, etc.
  - **File Mutations**: `touch`, `rm`, `mv`, `cp`, `chmod`, `chown`, `tee`, `sed`.
  - **Redirects**: Output redirection (`>` or `>>`) to files.
- **Resource Constraints**: Shell executions are bounded by timeouts (default `30` seconds) using `subprocess.run(timeout=timeout)` to prevent hangs.

---

## 4. Model Context Protocol (MCP) Safety

External MCP server tools are adapted into the agent registry via `MCPToolAdapter`. Because they resolve through the [ToolRouter](file:///home/tankaizokuo/Code/Nakama-Kun/src/nakama_kun/tools/router.py), they are bound by the same safety restrictions:
- All MCP tools that request file writes or run commands trigger the same verification and human-approval hooks.
- MCP client runtimes execute inside separate subprocess channels, isolating execution context.

---

## 5. Security Agent Verification

The cognitive verification workflow triggers [SecurityAgent](file:///home/tankaizokuo/Code/Nakama-Kun/src/nakama_kun/agents/security.py) checks before final review:
- **Secret Detection**: Scans proposed files for regex credentials (API keys, passwords, private keys).
- **Destructive Command Audit**: Scans execution logs to identify dangerous shell patterns (e.g. `rm -rf /`, `chmod 777`, piped downloads).

---

## 6. Threat Model

| Threat / Vector | Potential Impact | Nakama-kun Mitigations |
| :--- | :--- | :--- |
| **Path Traversal / Escape** | Reading or overwriting system files outside workspace root. | Enforced `assert_within_workspace` resolver constraints on all file tools. |
| **Malicious Code Modification** | Injecting vulnerabilities or backdoors into the project. | Mandatory Unified Diff review and human confirmation gates. |
| **Destructive Commands** | Host resource wiping, unsafe installs. | Regex-based command blocklist, timeout-guarded shells, and SecurityAgent audits. |
| **Secrets Leaking** | Committing private credentials or API keys. | SecurityAgent credentials detector scanner flags and blocks approvals. |
