# Nakama-kun Development Progression

## Overview

Nakama-kun is a Python-based AI agent inspired by OpenClaw. It combines a terminal-first workflow, tool-calling agents, workspace awareness, memory, and Telegram integration into a unified AI assistant capable of planning, coding, reviewing, and executing tasks.

---

# Phase 1 — Core CLI Foundation

## Objective

Create the initial command-line interface and user interaction layer.

## Features

- Custom CLI command

```bash
nakama wakeup
```

- Interactive terminal menu
- Rich formatted output
- ASCII banner
- Configuration loading

## Technology

- Typer
- Rich
- Questionary
- Pydantic Settings

## Deliverables

```text
nakama_kun/
│
├── cli/
│   ├── main.py
│   ├── menu.py
│   └── banner.py
│
├── config/
│   └── settings.py
│
└── main.py
```

## Completion Criteria

```bash
nakama wakeup
```

launches an interactive menu system.

---

# Phase 2 — Multi-Mode Architecture

## Objective

Implement independent operational modes.

## Menu Structure

```text
Main Menu
│
├── Agent Mode
├── Plan Mode
├── Ask Mode
├── Telegram Mode
└── Exit
```

## Deliverables

```text
modes/
│
├── agent.py
├── ask.py
├── plan.py
└── telegram.py
```

Each mode exposes:

```python
def run():
    pass
```

## Completion Criteria

User can navigate seamlessly between modes.

---

# Phase 3 — AI Integration Layer

## Objective

Connect Nakama-kun to large language models.

## Initial Provider

OpenRouter

## Supported Models

- GPT-5
- Claude Sonnet
- Claude Opus
- DeepSeek
- Qwen
- Llama

## Architecture

```text
ai/
│
├── client.py
├── prompts.py
├── models.py
└── config.py
```

## Responsibilities

### client.py

- Send requests
- Receive responses
- Stream output
- Error handling

### prompts.py

System prompts:

- Agent Prompt
- Planner Prompt
- Ask Prompt

## Completion Criteria

User enters:

```text
What is RAG?
```

and receives a streamed response.

---

# Phase 4 — Tool Calling Framework

## Objective

Transform Nakama-kun into an autonomous agent.

## Core Architecture

```text
User
 │
 ▼
Agent
 │
 ▼
LLM
 │
 ▼
Tool Router
 │
 ├── Read Tool
 ├── Write Tool
 ├── Search Tool
 ├── List Tool
 └── Execute Tool
```

## Tool Set

### Read File

```python
read_file(path)
```

### Write File

```python
write_file(path, content)
```

### List Files

```python
list_files()
```

### Search Files

```python
search_files(query)
```

### Execute Commands

```python
run_command(cmd)
```

## Completion Criteria

Agent can inspect and modify project files through controlled tool usage.

---

# Phase 5 — Planning Agent ✅

## Objective

Build a dedicated planner that reasons before execution.

## Behavior

Input:

```text
Build FastAPI backend
```

Output:

```text
Step 1: Create project structure

Step 2: Setup configuration

Step 3: Create API routes

Step 4: Add database layer

Step 5: Testing
```

## Characteristics

- No execution
- No file modifications
- Pure planning

## Completion Criteria

Produces actionable project plans.

---

# Phase 6 — Workspace Awareness

## Objective

Enable project understanding.

## Components

### Directory Scanner

Collects:

- Files
- Folders
- Extensions
- Sizes

### Workspace Analyzer

Detects:

- Language
- Framework
- Dependencies
- Entry points

### Context Builder

Produces:

```text
Project Type:
FastAPI

Entry Point:
main.py

Dependencies:
FastAPI
SQLAlchemy
Pydantic
```

## Completion Criteria

User can ask:

```text
Explain this project
```

and receive meaningful answers.

---

# Phase 7 — Telegram Integration

## Objective

Control Nakama-kun remotely.

## Stack

- python-telegram-bot

## Workflow

```text
Telegram
    │
    ▼
Message Handler
    │
    ▼
Agent
    │
    ▼
Tools
    │
    ▼
Response
```

## Features

- Chat with agent
- Read files
- Summarize code
- Plan tasks

## Completion Criteria

Remote interaction works identically to CLI mode.

---

# Phase 8 — Safety Layer

## Objective

Prevent unintended modifications.

## Workflow

```text
Request
   │
   ▼
Proposed Change
   │
   ▼
Diff Generation
   │
   ▼
Approval
   │
   ▼
Apply Change
```

## Features

- Diff preview
- Approval prompts
- Rollback support

## Technology

```python
difflib
```

## Completion Criteria

Every modification is reviewable before execution.

---

# Phase 9 — Memory System

## Objective

Persistent context across sessions.

## Stored Information

### Conversation Memory

```text
Previous chats
```

### Project Memory

```text
Workspace summaries
```

### User Preferences

```text
Preferred models
Coding style
Agent settings
```

## Storage

### MVP

```text
SQLite
```

### Advanced

```text
ChromaDB
LanceDB
PostgreSQL
```

## Completion Criteria

Agent remembers previous work and resumes tasks.

---

# Phase 10 — LangGraph Agent Orchestration

## Objective

Move from single-agent architecture to workflow-driven execution.

## Graph Structure

```text
User
 │
 ▼
Planner Node
 │
 ▼
Executor Node
 │
 ▼
Reviewer Node
 │
 ▼
Final Response
```

## Benefits

- Stateful execution
- Human approval checkpoints
- Multi-step reasoning
- Retry handling

## Completion Criteria

LangGraph orchestrates all agent workflows.

---

# Phase 11 — Retrieval Augmented Generation (RAG)

## Objective

Enable project-scale knowledge retrieval.

## Components

```text
Documents
    │
    ▼
Chunking
    │
    ▼
Embedding
    │
    ▼
Vector Database
    │
    ▼
Retriever
    │
    ▼
LLM
```

## Use Cases

- Large repositories
- Documentation search
- Historical task retrieval

## Completion Criteria

Agent answers questions using indexed project knowledge.

---

# Phase 12 — MCP Integration

## Objective

Connect external systems through Model Context Protocol.

## Potential Servers

- GitHub
- Notion
- Slack
- PostgreSQL
- Filesystem
- Browser

## Benefits

- Standardized tools
- Easy extensibility
- Interoperability

## Completion Criteria

External MCP servers can be attached dynamically.

---

# Phase 13 — Multi-Agent System

## Objective

Introduce specialized agents.

## Agent Hierarchy

```text
Planner Agent
      │
      ▼
Coder Agent
      │
      ▼
Reviewer Agent
      │
      ▼
Executor Agent
```

## Benefits

- Separation of concerns
- Higher reliability
- Better code quality

## Completion Criteria

Complex tasks are delegated across agents.

---

# Phase 14 — Voice Interface

## Objective

Hands-free interaction.

## Components

### Speech-to-Text

- Whisper

### Text-to-Speech

- ElevenLabs

## Workflow

```text
Voice
 │
 ▼
Whisper
 │
 ▼
Agent
 │
 ▼
ElevenLabs
 │
 ▼
Voice Reply
```

## Completion Criteria

Voice conversations are fully supported.

---

# Phase 15 — Web Interface

## Objective

Provide browser-based access.

## Options

### FastAPI + React

Production-ready

### Streamlit

Rapid development

### Gradio

Simple deployment

## Features

- Chat
- Workspace explorer
- Memory viewer
- Agent monitoring

## Completion Criteria

All CLI functionality available through web UI.

---

# Final Architecture

```text
Nakama-kun
│
├── CLI Layer
├── Telegram Layer
├── Web UI Layer
│
├── LangGraph Orchestrator
│
├── Agent System
│   ├── Planner
│   ├── Coder
│   ├── Reviewer
│   └── Executor
│
├── Tool Layer
│
├── Memory Layer
│
├── RAG Layer
│
├── MCP Layer
│
└── LLM Layer
    └── OpenRouter
```

# Recommended Stack

| Layer           | Technology                 |
| --------------- | -------------------------- |
| CLI             | Typer + Rich + Questionary |
| LLM             | OpenRouter                 |
| Agent Framework | LangGraph                  |
| Memory          | SQLite + ChromaDB          |
| RAG             | ChromaDB                   |
| Embeddings      | OpenAI / BGE               |
| Telegram        | python-telegram-bot        |
| Config          | Pydantic Settings          |
| Logging         | Loguru                     |
| Voice           | Whisper + ElevenLabs       |
| Local Models    | Ollama                     |
| Deployment      | Docker                     |

# MVP Milestone

A production-ready MVP is achieved after:

- Phase 1
- Phase 2
- Phase 3
- Phase 4
- Phase 5
- Phase 6
- Phase 8

At this point Nakama-kun becomes a fully functional OpenClaw-style AI coding agent capable of planning, understanding projects, safely editing files, and interacting through the terminal.
