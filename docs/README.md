# Nakama-kun Technical Documentation Suite

Welcome to the comprehensive technical documentation suite for **Nakama-kun**, an advanced, multi-agent AI developer companion designed to run in your terminal, manage local RAG contexts, trace execution memories, and run diagnostic evaluation checks on workspace projects.

---

## 1. Documentation Index

The following table catalogs all technical manuals and design documents detailing Nakama-kun's core systems, libraries, and protocols:

| Document | Purpose / Description |
| :--- | :--- |
| 🏗️ [System Architecture](file:///home/tankaizokuo/Code/Nakama-Kun/docs/ARCHITECTURE.md) | High-level system design, modular layers, dynamic dependency injection, and LangGraph workflow transitions. |
| 🖥️ [User Interfaces](file:///home/tankaizokuo/Code/Nakama-Kun/docs/UI.md) | Typer CLI commands, router state management, live Rich streaming, async Telegram bot mapping, and FastAPI WebSocket console dashboards. |
| 🤖 [Agent Roles & Prompts](file:///home/tankaizokuo/Code/Nakama-Kun/docs/AGENTS.md) | Input/output schemas, fallback patterns, and prompt structures for the Supervisor, Planner, Retriever, Coder, Test, Security, Verifier, Reviewer, and Final Response agents. |
| 🔄 [Retry & Fallback Mechanics](file:///home/tankaizokuo/Code/Nakama-Kun/docs/RETRY_SYSTEM.md) | LangGraph loop transitions, `RetryMemory` structure, state serialization, and duplicate action checks via cryptographic signatures. |
| 🔧 [Tool Calling Framework](file:///home/tankaizokuo/Code/Nakama-Kun/docs/TOOLS.md) | Schemas, dynamic parameter dispatchers, execution timeouts, and safety scopes for workspace manipulation tools. |
| 🛡️ [System Safety & Security](file:///home/tankaizokuo/Code/Nakama-Kun/docs/SAFETY.md) | Path traversal protection, `difflib`-based proposal validation, command execution blocklists, and human-in-the-loop approvals. |
| 🧠 [Memory & Context Systems](file:///home/tankaizokuo/Code/Nakama-Kun/docs/MEMORY.md) | Persistent SQLite workspace experience schemas, user preference scores, and dynamic planning prompt injections. |
| 🔍 [RAG Pipeline Manual](file:///home/tankaizokuo/Code/Nakama-Kun/docs/RAG.md) | Chunk segmentation rules (800-1200 chars), ONNX-based local embedders, token-budget context assemblies, and vector sync controls. |
| 🔌 [MCP Server Integration](file:///home/tankaizokuo/Code/Nakama-Kun/docs/MCP.md) | Stdio JSON-RPC subprocess protocol handling, namespace collision resolution, and MCP server health validation. |
| 📂 [Workspace Awareness Service](file:///home/tankaizokuo/Code/Nakama-Kun/docs/WORKSPACE_AWARENESS.md) | DirectoryScanner exclusions, Python AST function dependencies, NetworkX DAG visualization, and BFS Change Impact calculation. |
| ⚙️ [Configuration Reference](file:///home/tankaizokuo/Code/Nakama-Kun/docs/CONFIGURATION.md) | Pydantic-Settings environment keys, default values, `.env` file templates, and YAML configuration overlays. |
| 🗄️ [Database Architecture](file:///home/tankaizokuo/Code/Nakama-Kun/docs/DATABASE.md) | Entity-Relationship (ER) schemas for `nakama_memory.db` and `.rag/documents.db` with chunk tracking details. |
| 📊 [Observability & Telemetry](file:///home/tankaizokuo/Code/Nakama-Kun/docs/OBSERVABILITY.md) | Structured `loguru` streaming, provider request latency logs, token tracking, and sub-agent metric reports. |
| 🗺️ [Project Roadmap](file:///home/tankaizokuo/Code/Nakama-Kun/docs/PROJECT_ROADMAP.md) | Complete list of Phase 1-10 milestones, key deliverables, technical debt mitigation, and future development phases. |
| 📋 [Documentation Audit Report](file:///home/tankaizokuo/Code/Nakama-Kun/docs/DOCUMENTATION_AUDIT.md) | Verification checklist mapping classes, files, methods, code coverage, assumptions, and source files analyzed. |

---

## 2. Guided Reading Paths

Depending on your role and task in the Nakama-kun workspace, we recommend the following reading sequences:

### A. Developer Onboarding Path
Get up and running quickly with the development workflow:
1. ⚙️ [Configuration Reference](file:///home/tankaizokuo/Code/Nakama-Kun/docs/CONFIGURATION.md) — Set up your local environment and keys.
2. 🖥️ [User Interfaces](file:///home/tankaizokuo/Code/Nakama-Kun/docs/UI.md) — Launch the CLI or dashboard console.
3. 🔧 [Tool Calling Framework](file:///home/tankaizokuo/Code/Nakama-Kun/docs/TOOLS.md) — Learn how agents execute code modifications.
4. 📂 [Workspace Awareness Service](file:///home/tankaizokuo/Code/Nakama-Kun/docs/WORKSPACE_AWARENESS.md) — Understand file scanning and AST structures.

### B. Core Architecture & Workflow Review Path
Analyze Nakama-kun's distributed planning and execution logic:
1. 🏗️ [System Architecture](file:///home/tankaizokuo/Code/Nakama-Kun/docs/ARCHITECTURE.md) — Study the core layers and dependency graph.
2. 🤖 [Agent Roles & Prompts](file:///home/tankaizokuo/Code/Nakama-Kun/docs/AGENTS.md) — Deep-dive into LangGraph nodes and prompt constraints.
3. 🔄 [Retry & Fallback Mechanics](file:///home/tankaizokuo/Code/Nakama-Kun/docs/RETRY_SYSTEM.md) — Discover how agents recover from validation or test failures.
4. 🧠 [Memory & Context Systems](file:///home/tankaizokuo/Code/Nakama-Kun/docs/MEMORY.md) — Understand experience persistence.

### C. Security Audit & Safety Review Path
Verify runtime compliance and safety bounds:
1. 🛡️ [System Safety & Security](file:///home/tankaizokuo/Code/Nakama-Kun/docs/SAFETY.md) — Review command blocklists, workspace checks, and path escape protections.
2. 🔌 [MCP Server Integration](file:///home/tankaizokuo/Code/Nakama-Kun/docs/MCP.md) — Audit dynamic stdio subprocess executions and namespace rules.
3. 🗄️ [Database Architecture](file:///home/tankaizokuo/Code/Nakama-Kun/docs/DATABASE.md) — Check SQLite schema constraints.
