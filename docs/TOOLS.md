# Nakama-kun Tool System Reference

This document catalogs every core tool in Nakama-kun, detailing parameters, schemas, safety rules, and the execution dispatch cycle.

---

## 1. Tool Lifecycle and Registry Flow

1. **Discovery & Registration**: During startup, [build_default_registry](file:///home/tankaizokuo/Code/Nakama-Kun/src/nakama_kun/tools/__init__.py) instantiates and registers the six core local tools into [ToolRegistry](file:///home/tankaizokuo/Code/Nakama-Kun/src/nakama_kun/tools/registry.py). The `MCPManager` connects configured stdio servers and registers external tools.
2. **Tool Selection Optimization**: Prior to calling, the `CoderAgent` routes parameters through [ToolSelectionLayer](file:///home/tankaizokuo/Code/Nakama-Kun/src/nakama_kun/tools/selection.py) to clean redundant calls and filter parameters.
3. **Dispatch**: The [ToolRouter](file:///home/tankaizokuo/Code/Nakama-Kun/src/nakama_kun/tools/router.py) maps the LLM tool-call JSON string, validates input keys against Pydantic definitions, performs **RETRIEVAL-mode mutating safety checks**, and executes the tool.

---

## 2. Core Tool Catalog

### A. `read_file`
- **Purpose**: Reads full text content of a file within the workspace.
- **Arguments**:
  - `path` (string, required): File path to read (absolute or relative within workspace).
- **Return Values**: File contents on success, path verification errors on failure.
- **Safety Protections**: Boundary assertions via `assert_within_workspace`.
- **Usage Example**:
  `{"path": "src/nakama_kun/main.py"}`

### B. `write_file`
- **Purpose**: Overwrites or creates file content within the workspace.
- **Arguments**:
  - `path` (string, required): Destination file path.
  - `content` (string, required): Text content to write.
- **Return Values**: Success text with written character count, or human/safety rejections.
- **Safety Protections**: Asserts workspace containment. If `safety_manager` and `approval_provider` are wired, it submits proposals for unified diff rendering and halts for human y/n confirmation.
- **Usage Example**:
  `{"path": "version.txt", "content": "1.0.0"}`

### C. `list_files`
- **Purpose**: Lists files and folders recursively inside a targeted workspace directory.
- **Arguments**:
  - `path` (string, optional): Folder path. Defaults to `.` (workspace root).
- **Return Values**: List of text strings denoting whether each entry is a folder (`[dir]`) or file (`[file]`).
- **Safety Protections**: Asserts workspace containment.
- **Usage Example**:
  `{"path": "src/nakama_kun/core"}`

### D. `search_files`
- **Purpose**: Grep-style text/regex search across text-based code files.
- **Arguments**:
  - `query` (string, required): Pattern to scan.
  - `path` (string, optional): Folder path to restrict recursion. Defaults to `.`.
- **Return Values**: List of match entries matching `file_path:line_number: matched_line` (hard-capped to 50 matches).
- **Safety Protections**: Skips binary/compressed formats and hidden folders (e.g. `.git`, `.venv`).
- **Usage Example**:
  `{"query": "class CoderAgent"}`

### E. `search_vector_store`
- **Purpose**: Semantic vector search across code files, documentation, and historical database memory contexts.
- **Arguments**:
  - `query` (string, required): Similarity search question.
  - `limit` (integer, optional): Maximum matching documents. Defaults to 5.
- **Return Values**: Document snippets with file path, line range, and relevance scores.
- **Usage Example**:
  `{"query": "how does the verifier agent generate reports?", "limit": 3}`

### F. `run_command`
- **Purpose**: Runs a shell command on the host.
- **Arguments**:
  - `cmd` (string, required): Shell command.
  - `timeout` (integer, optional): Process time-out in seconds. Defaults to 30.
- **Return Values**: JSON string containing: `success`, `exit_code`, `stdout`, `stderr` (truncated to 8,000 characters).
- **Safety Protections**: Prohibited in retrieval mode. Scanned for mutating/destructive command patterns (e.g. package installers, mkdir, touches, file deletes).
- **Usage Example**:
  `{"cmd": "pytest tests/test_agents.py"}`
