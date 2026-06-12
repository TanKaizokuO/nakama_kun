# UI Documentation

This document describes the user interface of the `nakama_kun` project as implemented in the current codebase. The project is primarily a terminal-first AI agent CLI with an optional Telegram bot interface. There is no browser-based graphical frontend; the UI is composed from Typer command surfaces, Rich terminal rendering, Questionary interactive prompts, PyFiglet ASCII art, and Telegram Markdown messages.

## Product Shape

`nakama_kun` presents itself as "your nakama in the terminal": a companion-like AI agent for asking questions, planning implementation work, executing workspace tasks, inspecting project context, managing memory, and optionally exposing similar functions through Telegram.

The main interaction model is hierarchical:

```text
Typer CLI
  |
  +-- nakama_kun wakeup
  |     |
  |     +-- Startup banner
  |     +-- Main menu
  |           |
  |           +-- CLI
  |           |     |
  |           |     +-- Agent Mode
  |           |     +-- Plan Mode
  |           |     +-- Ask Mode
  |           |     +-- Explain Project
  |           |     +-- Memory Actions
  |           |     +-- Back
  |           |
  |           +-- Telegram
  |           +-- Exit
  |
  +-- nakama_kun explain
  +-- nakama_kun memory inspect
  +-- nakama_kun memory clear
```

The secondary interface is Telegram:

```text
Telegram Bot
  |
  +-- /start
  +-- /status
  +-- /ask <question>
  +-- /plan <goal>
  +-- /agent <task>
  +-- plain text message -> Ask behavior
```

## UI Technologies

The terminal interface is built from these libraries:

- Typer: command registration, help text, confirmation prompts, and command routing.
- Rich: panels, colors, tables, Markdown rendering, syntax-highlighted diffs, live streaming output, and formatted status/error text.
- Questionary: arrow-key menus, text prompts, and confirmation prompts.
- PyFiglet: large ASCII startup banner.

The Telegram interface uses:

- `python-telegram-bot`: bot lifecycle, command handlers, message sending, polling.
- Telegram Markdown parse mode: command formatting, bold/italic/code text, bullet lists, and status messages.

## Global Terminal Visual Language

The terminal UI has a neon terminal aesthetic, centered around cyan, magenta, green, yellow, and red. The palette is centralized in `src/nakama_kun/core/constants.py`:

- Primary: `bright_cyan`
- Secondary: `bright_magenta`
- Success: `bright_green`
- Warning: `yellow`
- Error: `bright_red`
- Muted: `dim white`
- Accent: `bright_white`
- CLI mode: `green`
- Telegram mode: `blue`
- Agent mode: `bright_cyan`
- Plan mode: `bright_yellow`
- Ask mode: `bright_magenta`

Questionary menus use a matching explicit hex theme in `src/nakama_kun/ui/menus.py`:

- Question mark: cyan, bold
- Question text: white, bold
- Answer: cyan, bold
- Pointer: magenta, bold
- Highlighted choice: magenta, bold
- Selected item: green
- Separators and instructions: dark gray, with instructions italicized
- Normal text: light gray
- Disabled text: dark gray italic

The overall feel is energetic and technical: bright mode-specific borders, compact terminal panels, live Markdown output, and minimal explanatory chrome once the user enters a mode.

## Shared Console Behavior

The project defines a shared Rich console in `src/nakama_kun/ui/console.py`:

```python
console = Console()
```

Most current UI modules import this shared console so terminal output remains visually consistent and testable. A few older modules instantiate their own `Console`, but the intended design is a single application-wide console.

`prompt_continue()` provides a common blocking footer for leaf states where the user needs time to read a result before the parent menu redraws:

```text
  Press Enter to continue...
```

It is rendered in dim text, with `Enter` emphasized in bold. `Ctrl-C` and `Ctrl-D` are swallowed silently and treated as a return.

## Startup Banner

The first visual element for the primary flow is the banner shown by `display_banner()` in `src/nakama_kun/ui/banner.py`.

The banner contains:

- Large PyFiglet ASCII art for the app name, currently rendered as `nakama kun`.
- A line-by-line gradient effect cycling through cyan and magenta Rich styles.
- A framed Rich `Panel`.
- A cyan border.
- Horizontal padding.
- A subtitle composed from the current phase and app name.
- A green version badge.

Default banner inputs:

```text
app_name: nakama kun
subtitle: Phase 1 . OpenClaw-style AI Agent CLI
version: v0.1.0
```

The active `wakeup` command overrides the subtitle and version:

```text
subtitle: Phase 5 . Planning Agent | <configured app name>
version: v0.4.0
```

The visual rhythm is:

```text
blank line
banner panel
blank line
```

The banner is meant to be visually striking and establishes the cyan/magenta palette used by the rest of the UI.

## Typer Root Command UI

The root app is defined in `src/nakama_kun/main.py` as `nakama_kun`.

Root command behavior:

- If invoked with no args, Typer shows help.
- Shell completion is disabled.
- Rich markup is enabled for help text.
- Pretty exceptions are enabled, but local variables are hidden.
- The root callback exists so Typer keeps `wakeup` as a real subcommand.

The root help copy describes the app as:

```text
An OpenClaw-style AI Agent CLI - your nakama in the terminal.

Run nakama_kun wakeup to get started.
```

Registered user-facing commands:

- `wakeup`: launches the interactive multi-mode UI.
- `explain`: analyzes the workspace and prints a structural explanation.
- `memory inspect`: displays persisted memory tables.
- `memory clear`: confirms and clears persisted memory.

## Main Menu

The active main menu is implemented in `src/nakama_kun/ui/menus.py`.

Before the selectable list appears, the UI prints a compact Rich panel:

```text
Choose Mode
```

Panel styling:

- Text: bold white
- Text alignment: centered
- Border: bright cyan
- Padding: vertical 0, horizontal 2

The Questionary selection prompt is intentionally given an empty label because the Rich panel already provides the title.

Choices, in order:

```text
CLI
Telegram
Exit
```

Interaction:

- Up/down arrows move the active item.
- Enter selects.
- Shortcuts are disabled.
- `Ctrl-C`, `Ctrl-D`, or `None` return `None`.

Navigation behavior:

- `CLI` launches the CLI sub-router.
- `Telegram` launches Telegram Mode.
- `Exit` returns the exit signal and triggers the farewell panel.
- Interrupting the top-level menu prints an interrupt message and exits.

## Exit and Interrupt UI

Normal exit from `wakeup` displays a centered Rich panel:

```text
Goodbye! 👋
```

Styling:

- Text: bold bright magenta
- Border: magenta
- Padding: vertical 0, horizontal 4
- Surrounding blank lines

Interrupting the top-level app with `Ctrl-C` renders:

```text
Interrupted - see you later! 👋
```

Styling:

- Bold yellow
- Surrounded by blank lines

Unexpected top-level errors render:

```text
Unexpected error: <exception>
Run with --debug for a full traceback.
```

Styling:

- The "Unexpected error:" label is bold red.
- The debug hint is dim.
- The process exits with status code 1.

## CLI Sub-Menu

The CLI sub-menu is owned by `CLIMode` and rendered by `show_cli_menu()` in `src/nakama_kun/ui/menus.py`.

Before the selectable list appears, the UI prints:

```text
Choose CLI Mode
```

Panel styling:

- Text: bold white
- Text alignment: centered
- Border: green
- Padding: vertical 0, horizontal 2

Choices, in order:

```text
Agent Mode
Plan Mode
Ask Mode
Explain Project
Memory Actions
Back
```

Interaction:

- Arrow-key Questionary selection.
- The same cyan/magenta Questionary style as the main menu.
- `Back`, `Ctrl-C`, or `Ctrl-D` returns to the top-level menu.
- Leaf modes return to this menu when they finish.

## Ask Mode UI

Ask Mode is implemented in `src/nakama_kun/modes/ask_mode.py`. It is a conversational REPL for general AI questions and streams model output into the terminal.

Entry panel:

```text
nakama_kun Ask Mode
Type your question, or 'exit' to return.
```

Panel styling:

- Title: `Ask Mode`
- Subtitle: current version, for example `v0.4.0`
- Border: bright magenta
- Body text: bold bright magenta
- Body alignment: centered

Memory restore state:

If a previous Ask conversation exists, the UI prints a dim restoration line:

```text
Restored active conversation: <title> (<message_count> messages)
```

Prompt:

```text
You:
```

The prompt uses the shared Questionary style.

Input behavior:

- Empty input is ignored and the prompt repeats.
- `exit` returns to the CLI sub-menu.
- `Ctrl-C` at the outer mode level prints `Returning to menu...` in yellow.
- `Ctrl-C` or `Ctrl-D` from the prompt returns to the CLI sub-menu.

Response prelude:

```text
nakama_kun:
Model: <configured OpenRouter model>

Thinking...
```

Styling:

- Assistant label: bold magenta
- Model line: bold dim
- Thinking line: italic dim

Streaming response:

- Responses are streamed token-by-token.
- Rich `Live` updates a `Markdown` renderable.
- Markdown formatting from the model is displayed in terminal-native Rich Markdown.
- After streaming completes, a final blank line is printed.

Error states:

- Missing API key: `OpenAI API key not found.`
- Rate limit: `Rate limit exceeded. Try again later.`
- Network error: `Unable to reach provider.`
- Invalid model: `Configured model unavailable.`
- Generic AI error: `AI Error: <message>`
- Unexpected error: `Unexpected error: <message>`

All error messages are bold red and surrounded by blank lines.

## Plan Mode UI

Plan Mode is implemented in `src/nakama_kun/modes/plan_mode.py`. It is a planning-only REPL that asks the model to decompose implementation goals without executing tools or modifying files.

Entry panel:

```text
nakama_kun Plan Mode
Describe your implementation goal, or type 'back'/'exit' to return.
```

Panel styling:

- Title: `Plan Mode`
- Subtitle: current version
- Border: bright yellow
- Body text: bold bright yellow
- Body alignment: centered

Memory restore state:

If a previous planning session exists, the UI prints:

```text
Restored active planning session: <title> (<message_count> messages)
```

Styling is dim, followed by a blank line.

Prompt:

```text
Goal:
```

Input behavior:

- Empty input is ignored.
- `back` or `exit` returns to the CLI sub-menu.
- `Ctrl-C` at the outer mode level prints `Returning to menu...` in yellow.

Response prelude:

```text
nakama_kun Planner:
Model: <configured OpenRouter model>

Planning...
```

Styling:

- Planner label: bold yellow
- Model line: bold dim
- Planning line: italic dim

Structured plan rendering:

When the model output can be parsed into the project `Plan` model, the UI renders a Rich panel titled:

```text
📋 Planned Implementation
```

Panel styling:

- Title: bold yellow
- Border: yellow
- `expand=False`, so it wraps content tightly instead of filling the full terminal width.

Sections inside the panel:

- `Goal Summary`: bright yellow heading; summary body italic.
- `Target Files/Modules`: bold cyan heading; each target prefixed with a bullet.
- `Assumptions`: bold cyan heading; each assumption prefixed with a bullet.
- `Execution Steps`: bold green heading; numbered steps.
- `Risks & Hazards`: bold red heading; each risk prefixed with a warning symbol.
- `Validation Checklist`: bold magenta heading; each item prefixed with an empty checkbox.

Unstructured plan fallback:

If JSON parsing fails, the raw model output is rendered as Rich Markdown inside a yellow panel titled:

```text
📋 Implementation Plan
```

Error states:

- Missing API key: `API key not found.`
- Rate limit: `Rate limit exceeded. Try again later.`
- Network error: `Unable to reach provider.`
- Invalid model: `Configured model unavailable.`
- Generic AI error: `AI Error: <message>`
- Unexpected error: `Unexpected error: <message>`

All are bold red and surrounded by blank lines.

## Agent Mode UI

Agent Mode is implemented in `src/nakama_kun/modes/agent_mode.py`. It accepts a task and runs an agentic workflow with planning, tool execution, verification, review, retries, and final response generation.

Entry panel:

```text
nakama_kun Agent Mode
Describe your task, or type 'exit' to return.
```

Panel styling:

- Title: `Agent Mode`
- Subtitle: current version
- Border: bright cyan
- Body text: bold bright cyan
- Body alignment: centered

Tool availability line:

Immediately after the panel, Agent Mode lists the registered tools in dim text:

```text
Tools available: read_file, write_file, list_files, search_files, run_command
```

The exact list depends on the default registry.

Prompt:

```text
Task:
```

Input behavior:

- Empty input is ignored.
- `exit` returns to the CLI sub-menu.
- `Ctrl-C` at the outer mode level prints `Returning to menu...` in yellow.

Execution visibility:

The current LangGraph-based `_agent_loop()` does most planner, executor, verifier, and reviewer progress through Loguru logs rather than direct terminal UI. The terminal user sees:

- The Agent Mode shell.
- Tool approval prompts when a write operation proposes a file change.
- The final answer when the workflow completes.
- Any high-level exceptions surfaced by the mode.

Final answer rendering:

When a final answer is available, the UI prints:

```text
nakama_kun:
Model: <configured OpenRouter model>
```

Then the final answer is rendered as Rich Markdown through `Live`, similar to Ask Mode. Unlike Ask Mode, the current implementation updates the live renderable once with the complete final answer rather than streaming tokens progressively.

Legacy tool-call rendering:

`AgentMode` still contains `_execute_tool_call()`, which renders per-tool lines such as:

```text
  -> Tool call: <name> args=<json-preview>
  ✓ Tool '<name>' (ok)
  ✗ Tool '<name>' error: <message>
```

This is not the primary path for the current LangGraph workflow, but it documents the intended visual language for direct tool-call feedback:

- Tool call prelude: dim, with tool name bold.
- Successful result: dim, check mark.
- Tool error: yellow or red with cross mark.
- Arguments are JSON-encoded and truncated to 120 characters.

Error states:

- Missing API key: `API key not found.`
- Rate limit: `Rate limit exceeded. Try again later.`
- Network error: `Unable to reach provider.`
- Invalid model: `Configured model unavailable.`
- Generic AI error: `AI Error: <message>`
- Unexpected error: `Unexpected error: <message>`

All are bold red and surrounded by blank lines.

## Safety Approval UI

File writes can go through `TerminalApprovalProvider` in `src/nakama_kun/safety/terminal.py`.

When the agent proposes a change, the terminal displays a diff review panel.

Panel title:

```text
⚠️ Proposed Change: <CHANGE_TYPE> '<filename>'
```

Title styling:

- Bold yellow

Panel subtitle:

```text
Path: <full path>
```

Panel body:

- The proposed unified diff is rendered with Rich `Syntax`.
- Lexer: `diff`
- Theme: `monokai`
- Line numbers: disabled
- Word wrap: enabled

Panel styling:

- Border: yellow
- Padding: vertical 1, horizontal 2

Confirmation prompt:

```text
Do you approve applying this change?
```

Behavior:

- Default answer is `False`.
- `Ctrl-C` or `Ctrl-D` rejects the proposal.
- Approved proposals print a bold green success line.
- Rejected proposals print a bold red rejection line.

Result messages:

```text
✓ Change approved and applied.
✗ Change rejected by user.
```

This approval UI is the most explicit human-in-the-loop surface in the project.

## Explain Project UI

There are two ways to access workspace explanation:

- `nakama_kun explain`
- `wakeup` -> `CLI` -> `Explain Project`

Both use `WorkspaceContextBuilder` and render a Rich Markdown summary.

Loading message:

```text
Analyzing project...
```

Styling:

- Bold yellow

Result panel:

```text
Workspace Explanation
```

Panel styling:

- Title: bold green
- Border: green
- Body: Rich Markdown generated from the workspace summary

Failure state:

```text
Failed to analyze project: <exception>
```

Styling:

- Bold red

The in-menu version prints extra blank lines around the panel before returning to the CLI sub-menu.

## Memory UI

Memory has two UI entry points:

- `nakama_kun memory inspect`
- `wakeup` -> `CLI` -> `Memory Actions`

### Memory Disabled State

When memory is disabled, the command UI prints a yellow panel:

```text
Memory is currently disabled in settings. No records to display.
```

Panel:

- Title: `Memory Inspection`
- Border: yellow

The in-menu Memory Actions UI uses a similar yellow panel:

```text
Memory is currently disabled in configuration settings.
```

### Memory Inspect Command

When memory is enabled, `memory inspect` first prints a cyan panel:

```text
SQLite Memory Database: `<db_path>`
```

Panel:

- Title: `Memory System`
- Border: cyan
- Database label: bold cyan
- Path is shown in inline-code style.

Then it renders three Rich tables.

Recent Conversations table:

- Title: `Recent Conversations`
- `expand=True`
- Columns:
  - `ID`: dim, max width 36
  - `Title`: magenta
  - `Mode`: green
  - `Created At`: yellow

Recent Agent Tasks table:

- Title: `Recent Agent Tasks`
- `expand=True`
- Columns:
  - `ID`: dim, max width 36
  - `Description`: white
  - `Status`: bold green column style, with cell-specific colors
  - `Created At`: yellow

Task status colors:

- `done`: green
- `running`: yellow
- all other statuses: red

User Preferences table:

- Title: `User Preferences`
- `expand=True`
- Columns:
  - `Key`: bold cyan
  - `Value`: white

### Memory Actions Menu

The interactive Memory Actions submenu is a Questionary select prompt:

```text
Memory Actions:
```

Choices:

```text
Inspect Conversations
Inspect Tasks
Inspect Preferences
Clear All Memory
Back
```

The submenu uses the same `_MENU_STYLE` as the main and CLI menus.

Each inspect action renders a single Rich table matching the command-level tables above.

Clear action:

Confirmation prompt:

```text
Are you sure you want to delete all saved memory?
```

Default:

- `False`

Success output:

```text
Memory wiped successfully.
```

Styling:

- Bold green

Failure output:

```text
Failed to wipe memory: <exception>
```

Styling:

- Bold red

### Memory Clear Command

The non-interactive command route uses Typer confirmation:

```text
Are you sure you want to delete all Nakama-kun memory?
```

If declined:

```text
Aborted.
```

Styling:

- Yellow

If memory is disabled:

```text
Memory is disabled. Nothing to clear.
```

Styling:

- Yellow

On successful clear, it prints a green panel:

```text
Successfully wiped the memory database!
```

Panel:

- Title: `Wipe Complete`
- Border: green

On failure:

```text
Failed to clear memory: <exception>
```

Styling:

- Bold red

## Telegram Mode Terminal UI

Telegram Mode is selected from the top-level menu and implemented in `src/nakama_kun/modes/telegram_mode.py`.

Entry panel:

```text
Telegram Mode Starting...
```

Styling:

- Text: bold blue
- Alignment: centered
- Border: blue
- Padding: vertical 0, horizontal 4

Missing token state:

If `TELEGRAM_BOT_TOKEN` is not set:

```text
Error: TELEGRAM_BOT_TOKEN environment variable is not set.
Please set TELEGRAM_BOT_TOKEN in your .env file.
```

Styling:

- Error line: bold red
- Instruction line: dim
- Then `prompt_continue()` waits for Enter before returning.

Empty allow-list warning:

If `TELEGRAM_ALLOWED_CHAT_IDS` is empty:

```text
Warning: TELEGRAM_ALLOWED_CHAT_IDS is empty. No one will be authorized to access the bot.
```

Styling:

- Bold yellow

Running state:

After successful service start, the terminal displays:

```text
Telegram Bot is running! Press Ctrl-C to stop.
```

Panel styling:

- Text: bold green
- Alignment: centered
- Border: green
- Padding: vertical 0, horizontal 4

Shutdown state:

On `Ctrl-C`:

```text
Stopping Telegram bot...
Telegram bot stopped cleanly.
```

Styling:

- Stopping line: yellow
- Stopped line: green

Unexpected startup failure:

```text
Unexpected error starting Telegram bot: <exception>
```

Styling:

- Bold red
- Then `prompt_continue()` waits before returning.

## Telegram Bot Chat UI

Telegram bot handlers live in `src/nakama_kun/telegram/handlers.py`. The chat UI uses Markdown formatting and emoji-prefixed status messages.

### Authorization

Every bot handler is wrapped in `authorized_only()`.

Unauthorized users receive:

```text
⚠️ Access Denied: This bot is private and configured for authorized chats only.
```

No Markdown parse mode is specified for this denial message.

Authorized updates are logged but do not produce extra chat UI.

### `/start`

The `/start` command sends a welcome message using Markdown:

```text
👋 Welcome to *nakama_kun* Telegram Bot!

Here are the available commands:
• `/start` - Display this welcome message
• `/status` - Check the bot and AI model status
• `/ask <question>` - Ask a general question
• `/plan <goal>` - Generate an implementation plan
• `/agent <task>` - Run an autonomous agent to accomplish a task

Any plain text messages will be routed to Ask Mode by default.
```

Visual traits:

- Bot name is bold.
- Commands are inline code.
- Bullets use the Telegram bullet character.
- Plain text describes the default routing behavior.

### `/status`

The `/status` command sends:

```text
🤖 *nakama_kun Status*

• *System*: Active
• *Model*: `<configured model>`
• *API URL*: `https://openrouter.ai/api/v1`
```

Visual traits:

- Title is bold.
- Field labels are bold.
- Model and URL are inline code.
- Uses Markdown parse mode.

### `/ask <question>`

If the command has no args, the bot replies:

```text
⚠️ Usage: `/ask <your question>`
```

With a valid question, the bot first sends a status message:

```text
🤔 _Thinking..._
```

The final model response replaces that status message when possible. If the response is too long, it is split into chunks and later chunks are sent as additional messages.

Markdown behavior:

- The first chunk tries to edit the status message using Markdown.
- If Markdown parsing fails, it retries without parse mode.
- Subsequent chunks are sent as Markdown, with fallback to plain text.

Error behavior:

```text
❌ *Error*: <exception>
```

If Markdown parsing fails, it falls back to:

```text
❌ Error: <exception>
```

### Plain Text Messages

Plain text messages that do not start with `/` are routed to the same Ask logic as `/ask`.

Messages that start with `/` are ignored by the plain text handler because command handlers own those.

### `/plan <goal>`

If the command has no args, the bot replies:

```text
⚠️ Usage: `/plan <goal>`
```

With a valid goal, the bot first sends:

```text
📋 _Planning implementation..._
```

Structured plans are formatted into Telegram Markdown:

```text
📋 *Planned Implementation*

*Goal Summary*
_<goal summary>_

*Target Files/Modules*
• `<target>`

*Assumptions*
• <assumption>

*Execution Steps*
1. <step>

*Risks & Hazards*
⚠️ <risk>

*Validation Checklist*
☐ <item>
```

If structured parsing fails, raw plan text is sent instead.

The response is delivered through the same chunking/editing helper used by Ask.

### `/agent <task>`

If the command has no args, the bot replies:

```text
⚠️ Usage: `/agent <task description>`
```

With a valid task, the bot first sends:

```text
🤖 _Starting agent loop..._
⚙️ _Running workspace tools..._
```

The final agent answer replaces that status message when possible, with chunked follow-up messages for long responses.

The Telegram Agent path uses auto-approval for write operations, so users do not see the terminal diff approval UI inside Telegram.

### Telegram Message Chunking

`src/nakama_kun/telegram/utils.py` enforces a default maximum chunk size of 4000 characters.

Splitting behavior:

- Short messages are sent as one chunk.
- Long messages are split by preserving lines when possible.
- Single lines longer than the maximum are split by character range.
- If a status message id is available, the first chunk edits that message.
- Remaining chunks are sent as new messages.
- Markdown parse failures fall back to plain text.

## Older Menu Module

`src/nakama_kun/ui/menu.py` contains an older top-level menu implementation with:

- `MenuChoice.CLI`
- `MenuChoice.TELEGRAM`
- `MenuChoice.EXIT`
- Stub handlers that print "Starting CLI mode..." and "Starting Telegram mode..."
- A magenta goodbye panel

The active `wakeup` path imports from `src/nakama_kun/ui/menus.py`, not this older module. The older module is still useful as historical UI context but should not be treated as the primary runtime menu.

## Navigation Semantics

Navigation is implemented with `NavSignal`:

- `CONTINUE`: stay in the current loop.
- `BACK`: return to the parent menu.
- `EXIT`: terminate the application.

Mode behavior:

- The top-level menu loops until `EXIT`.
- CLI Mode loops until `Back` or a child returns `EXIT`.
- Ask, Plan, Agent, and Telegram return `BACK` when finished.
- `Ctrl-C` in a leaf mode generally returns to the parent menu.
- `Ctrl-C` in the top-level flow exits the whole application.

The result is a modal but forgiving terminal UI: leaf modes are easy to leave, while top-level exit is explicit.

## Error Presentation Pattern

The project uses a consistent terminal error pattern:

- Errors are red.
- Expected provider errors have short human-readable messages.
- Unexpected errors include exception text.
- Most mode-level errors are surrounded by blank lines.
- Top-level unexpected errors include a dim debug hint.

Common provider-facing error messages:

```text
API key not found.
OpenAI API key not found.
Rate limit exceeded. Try again later.
Unable to reach provider.
Configured model unavailable.
AI Error: <message>
Unexpected error: <message>
```

Telegram error messages use a leading cross mark and Markdown bold label:

```text
❌ *Error*: <message>
```

## Loading and Progress States

The terminal UI uses lightweight progress text instead of spinners:

- `Analyzing project...`
- `Thinking...`
- `Planning...`
- `Tools available: ...`
- `Telegram Bot is running! Press Ctrl-C to stop.`

Ask Mode streams live Markdown, so the model response itself becomes the progress indicator after `Thinking...`.

Plan Mode does not stream; it prints `Planning...`, waits, then renders a complete plan panel.

Agent Mode does not currently surface each LangGraph node in the terminal. Most internal workflow progress goes to logs. The user sees the final answer and any approval prompts.

Telegram uses editable status messages:

- `🤔 Thinking...`
- `📋 Planning implementation...`
- `🤖 Starting agent loop... / ⚙️ Running workspace tools...`

The status message is replaced by the first response chunk.

## Markdown Rendering

The terminal and Telegram UIs both accept Markdown-like output, but through different renderers.

Terminal:

- Rich `Markdown` renders Ask responses, Agent final answers, unstructured plans, and workspace explanations.
- Rich handles headings, lists, code blocks, emphasis, tables where supported, and terminal wrapping.

Telegram:

- Telegram Markdown parse mode renders bold, italic, inline code, and simple list structures.
- The code includes fallback paths because generated Markdown may be invalid for Telegram.

## Tables

Tables are used only for memory inspection.

Design characteristics:

- Full-width expansion is enabled with `expand=True`.
- Table titles summarize the data class.
- IDs are dimmed and constrained to avoid dominating the layout.
- Semantic colors distinguish fields:
  - Magenta titles.
  - Green modes/status.
  - Yellow timestamps.
  - Cyan keys/database labels.
  - Red/yellow/green status coloring for task outcomes.

No table pagination exists; command-level queries limit most lists to 10 rows, while the interactive memory actions use repository defaults.

## Panels

Panels are the main structural primitive for terminal screens.

Common panel uses:

- Startup identity: large banner.
- Menu section title: `Choose Mode`, `Choose CLI Mode`.
- Mode entry headers: Ask, Plan, Agent, Telegram.
- Structured output: plans, workspace explanations, memory status, wipe success.
- Safety approval diffs.
- Exit and lifecycle messages.

Panel border colors communicate context:

- Cyan: primary/menu/agent identity.
- Green: CLI, success, workspace explanation.
- Magenta: exit and Ask mode.
- Yellow: Plan mode, warnings, safety approvals.
- Blue: Telegram.
- Red is usually reserved for inline errors rather than panel borders.

## Accessibility and Keyboard Use

The terminal UI is keyboard-driven:

- Arrow keys navigate menus.
- Enter confirms selections.
- Typed commands drive REPL modes.
- `exit` and/or `back` leave REPL modes.
- `Ctrl-C` and `Ctrl-D` are handled gracefully in most prompts.

The UI relies heavily on color, but most important states also include text labels:

- `Error`
- `Warning`
- `Tools available`
- `Goal Summary`
- `Execution Steps`
- `Validation Checklist`
- `Access Denied`

Some status icons and emoji provide additional signal but are not the only indicator.

## Implementation Notes and Current UI Gaps

- The active menu module is `ui/menus.py`; `ui/menu.py` is older and stub-oriented.
- `ui/banner.py` creates its own `Console` instead of importing the shared console from `ui/console.py`.
- Several CLI modules also instantiate local `Console` objects. The project comments indicate the shared console is the desired long-term pattern.
- Agent Mode's current LangGraph workflow does not show per-node progress in the terminal. Users see the final answer, errors, and safety approval prompts, but not a live planner/executor/verifier timeline.
- Plan Mode uses some Unicode symbols in plan rendering, including a clipboard title, bullet markers, warning markers, and checkbox markers.
- README and constants differ slightly in phase descriptions and default banner examples; runtime `wakeup` uses `CURRENT_PHASE` and `APP_VERSION` from `core/constants.py`.
- Telegram Mode is fully wired to start the bot service when configured, despite some older project documentation describing it as a placeholder.
- Telegram `/agent` uses auto-approval for file writes, so there is no chat-native diff approval experience.
- Telegram responses are split at 4000 characters, below Telegram's hard message limit, to preserve room for formatting.

## Source Map

Primary UI source files:

- `src/nakama_kun/main.py`: Typer application and command registration.
- `src/nakama_kun/cli/wakeup.py`: startup flow, banner invocation, router loop, exit/error UI.
- `src/nakama_kun/cli/commands.py`: `explain` command UI.
- `src/nakama_kun/cli/memory_cmd.py`: command-level memory inspection and clearing UI.
- `src/nakama_kun/ui/banner.py`: PyFiglet/Rich startup banner.
- `src/nakama_kun/ui/console.py`: shared console and continue prompt.
- `src/nakama_kun/ui/menus.py`: active main menu and CLI sub-menu.
- `src/nakama_kun/ui/menu.py`: older menu/stub implementation.
- `src/nakama_kun/modes/cli_mode.py`: CLI sub-router, explain action, interactive memory actions.
- `src/nakama_kun/modes/ask_mode.py`: streaming Ask REPL.
- `src/nakama_kun/modes/plan_mode.py`: planning REPL and structured plan panel.
- `src/nakama_kun/modes/agent_mode.py`: agent task REPL and final answer rendering.
- `src/nakama_kun/modes/telegram_mode.py`: terminal lifecycle UI for Telegram bot mode.
- `src/nakama_kun/safety/terminal.py`: terminal diff approval UI.
- `src/nakama_kun/telegram/handlers.py`: Telegram command/message responses.
- `src/nakama_kun/telegram/utils.py`: Telegram response chunking and status message replacement.
- `src/nakama_kun/core/constants.py`: app metadata, color tokens, navigation signals.

