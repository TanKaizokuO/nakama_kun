# nakama_kun 🤖

> **Your nakama in the terminal** — an OpenClaw-style AI Agent CLI.

[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org)
[![uv](https://img.shields.io/badge/managed%20by-uv-purple)](https://docs.astral.sh/uv/)
[![Phase](https://img.shields.io/badge/phase-5-green)](#roadmap)

---

## Overview

`nakama_kun` is a modular, extensible AI Agent CLI built for power-users who
want a beautiful, keyboard-driven terminal experience. Phase 5 adds a dedicated
**Plan Mode** REPL that produces clean, structured plans for implementation goals
without executing tools or writing files directly.

---

## Tech Stack

| Library | Role |
|---|---|
| **Typer** | CLI framework (commands, flags) |
| **Rich** | Terminal styling (panels, colours, markup, trees, markdown) |
| **Questionary** | Arrow-key interactive prompts |
| **PyFiglet** | ASCII art banner |
| **Pydantic** | Structured models and validation |
| **OpenAI** | LLM API client |

---

## Project Structure

```text
nakama_kun/
│
├── src/
│   └── nakama_kun/
│       ├── __init__.py          # Package metadata
│       ├── main.py              # Typer app root + command registration
│       ├── cli/
│       │   ├── __init__.py
│       │   └── wakeup.py        # `nakama_kun wakeup` command
│       │
│       ├── ui/
│       │   ├── __init__.py
│       │   ├── banner.py        # PyFiglet + Rich ASCII banner
│       │   └── menus.py         # Questionary interactive menus
│       │
│       ├── ai/
│       │   ├── models/          # Structured messages, responses, and plans
│       │   ├── services/        # Chat and Planner orchestration services
│       │   └── prompts/         # Mode system prompts
│       │
│       ├── modes/               # Execution loops (Agent, Ask, Plan, Telegram)
│       └── tools/               # Agent workspace tools (read, write, command execution)
│
├── pyproject.toml
├── README.md
└── .gitignore
```

---

## Installation

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager

### Install dependencies & CLI

```bash
# Install all dependencies into a virtual environment
uv sync

# Install the nakama_kun script into the venv
uv pip install -e .
```

### Activate the environment (optional — or use `uv run`)

```bash
source .venv/bin/activate
```

---

## Usage

```bash
# Via uv (no activation needed)
uv run nakama_kun wakeup

# Or after activation
nakama_kun wakeup
```

You will see:
1. A large PyFiglet ASCII banner styled with Rich gradients
2. An arrow-key interactive menu: **CLI** / **Telegram** / **Exit**

---

## Keyboard Controls

| Key | Action |
|---|---|
| ↑ / ↓ | Navigate menu |
| Enter | Select |
| Ctrl-C | Graceful exit / return |

---

## Roadmap

- [x] **Phase 1**: Core CLI Skeleton
- [x] **Phase 2**: Multi-Mode Architecture
- [x] **Phase 3**: AI Integration Layer (OpenRouter, Streaming Ask Mode)
- [x] **Phase 4**: Tool Calling Framework (Agent Mode with workspace tools)
- [x] **Phase 5**: Planning Agent (Plan Mode with structured task decomposition)
- [ ] **Phase 6**: Workspace Awareness
- [ ] **Phase 7**: Telegram Bot
- [ ] **Phase 8**: Safety Layer (Diff approval)


---

## Development

```bash
# Install dev tools (pytest, ruff, mypy)
uv sync --dev

# Lint
uv run ruff check src/

# Type-check
uv run mypy src/

# Run tests
uv run pytest
```

---

## License

Apache-2.0 — see [LICENSE](LICENSE) for details.
