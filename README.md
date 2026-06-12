# nakama_kun 🤖

> **Your nakama in the terminal** — an OpenClaw-style AI Agent CLI.

[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org)
[![uv](https://img.shields.io/badge/managed%20by-uv-purple)](https://docs.astral.sh/uv/)
[![Phase](https://img.shields.io/badge/phase-8-green)](#roadmap)

---

## Overview

`nakama_kun` is a modular, extensible AI Agent CLI built for power-users who want a beautiful, keyboard-driven terminal experience. It is designed to act as a reliable companion (nakama) for coding tasks, system exploration, and workspace management.

With a rich suite of interactive CLI modes, safety guardrails, persistent SQLite memory, workspace indexing, and a Telegram Bot interface, `nakama_kun` offers a comprehensive developer assistant experience.

---

## Core Features

- **Agent Mode**: A robust execution loop equipped with:
  - **Verification Layer**: Validates tool execution results, confirming file writes/deletions on disk and parsing test runner outputs (`pytest`/`unittest`).
  - **Evidence Store**: Retains all execution history (tool results, file read/write states, command outputs) as an immutable record of actions taken.
  - **Retry Memory**: Feeds previous tool failures, validation errors, and successes back into the planner to prevent repetitive loop behaviors and allow dynamic adaptation.
- **Plan Mode**: A dedicated Planning REPL that produces clean, structured, and decomposed task lists for implementation goals without executing tools or modifying files.
- **Ask Mode**: A lightweight, interactive Q&A mode for quick explanations and queries.
- **Workspace Awareness**: Scans and indexes project structure, file sizes, extensions, and code semantics, producing rich workspace summaries for grounding agent prompts.
- **Telegram Integration**: A Telegram Bot service exposing agent and workspace capabilities, allowing remote interactions and queries.
- **Safety Layer**: Guardrails including path escaping checks, unified diff visualizations, a multi-provider approval workflow, and a full rollback system for undoing file creations/updates/deletions.
- **Persistent Memory**: SQLite database backend storing conversations, user preferences, and agent tasks across CLI sessions.

---

## Tech Stack

| Library | Role |
|---|---|
| **Typer** | CLI framework (commands, flags) |
| **Rich** | Terminal styling (panels, columns, trees, markdown) |
| **Questionary** | Arrow-key interactive prompts and menus |
| **PyFiglet** | ASCII art banners |
| **Pydantic** | Structured models and environment configurations |
| **OpenAI** | LLM API client |
| **LangGraph** | Agent workflow orchestration |
| **Python Telegram Bot** | Telegram API wrapper for the Bot Mode |

---

## Project Structure

```text
nakama_kun/
│
├── src/
│   └── nakama_kun/
│       ├── __init__.py          # Package metadata
│       ├── main.py              # Typer app root & command registration
│       │
│       ├── cli/
│       │   ├── __init__.py
│       │   ├── commands.py      # Core CLI commands definitions
│       │   ├── memory_cmd.py    # `memory` command suite
│       │   └── wakeup.py        # `wakeup` command
│       │
│       ├── config/              # Environment configurations & memory settings
│       ├── core/                # Constants and helper utilities
│       │
│       ├── ui/
│       │   ├── __init__.py
│       │   ├── banner.py        # PyFiglet + Rich ASCII banners
│       │   └── menus.py         # Questionary interactive menus
│       │
│       ├── ai/
│       │   ├── models/          # Structured messages, responses, and plans
│       │   ├── services/        # Chat & Planner orchestration
│       │   └── prompts/         # Mode system prompts
│       │
│       ├── modes/               # Execution loops (Agent, Ask, Plan, Telegram)
│       ├── tools/               # Agent workspace tools (read, write, command execution)
│       ├── memory/              # SQLite persistent memory repository & interfaces
│       ├── workspace/           # Project indexing and context builders
│       ├── safety/              # Path validations, diff generator, and rollback manager
│       └── telegram/            # Bot handlers, services, and utils
│
├── pyproject.toml
├── README.md
└── .gitignore
```

---

## Installation & Setup

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager

### Installation

```bash
# Clone the repository
git clone https://github.com/your-username/Nakama-Kun.git
cd Nakama-Kun

# Sync virtual environment and dependencies
uv sync --dev

# Install the package in editable mode
uv pip install -e .
```

---

## Usage

Start the interactive terminal application:
```bash
uv run nakama_kun wakeup
```

Alternatively, run specific CLI commands directly:
```bash
# Analyze and explain the current workspace structure
uv run nakama_kun explain

# Inspect persistent memory database contents
uv run nakama_kun memory inspect

# Clear all persistent records
uv run nakama_kun memory clear
```

---

## Keyboard Controls (Terminal UI)

| Key | Action |
|---|---|
| ↑ / ↓ | Navigate menus / select options |
| Enter | Confirm selection |
| Ctrl-C | Gracefully cancel current option / return to parent menu |

---

## Development & Testing

We use `pytest` for unit and integration testing. Run tests locally using:

```bash
# Run pytest ignoring mocks/fixtures in Test1 and Test2
uv run python -m pytest --ignore=tests/Test1 --ignore=tests/Test2

# Run lint checks with ruff
uv run ruff check src/

# Run type checks with mypy
uv run mypy src/
```

---

## Roadmap

- [x] **Phase 1**: Core CLI Skeleton
- [x] **Phase 2**: Multi-Mode Architecture
- [x] **Phase 3**: AI Integration Layer (OpenRouter, Streaming Ask Mode)
- [x] **Phase 4**: Tool Calling Framework (Agent Mode with workspace tools)
- [x] **Phase 5**: Planning Agent (Plan Mode with structured task decomposition)
- [x] **Phase 6**: Workspace Awareness (Context builder & project indexer)
- [x] **Phase 7**: Telegram Bot (Remote interaction and services)
- [x] **Phase 8**: Safety Layer (Diff approval, validation, and rollback support)

---

## License

Apache-2.0 — see [LICENSE](LICENSE) for details.
