"""
modes/agent_mode.py — Agent Mode: agentic execution loop with tool calling.

Phase 4: The agent receives a user task, calls workspace tools in a loop,
appends tool results to the message history, and continues until the LLM
produces a final answer (finish_reason == "stop") or the iteration limit is hit.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import questionary
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from nakama_kun.ai.exceptions import (
    AIError,
    APIKeyNotFoundError,
    InvalidModelError,
    NetworkError,
    RateLimitError,
)
from nakama_kun.ai.models.message import Message, ToolCall
from nakama_kun.ai.services.chat_service import ChatService
from nakama_kun.core.constants import APP_VERSION, Colours, NavSignal
from nakama_kun.modes.base import BaseMode
from nakama_kun.tools import ToolRegistry, ToolRouter, build_default_registry
from nakama_kun.ui.console import console
from nakama_kun.ui.menus import _MENU_STYLE

# Maximum tool-call rounds per single user request before forcing a stop.
_MAX_ITERATIONS: int = 10


class AgentMode(BaseMode):
    """Agent Mode — agentic execution loop with workspace tool access.

    Each user request kicks off a multi-round loop:
      1. Build message list (system + history + new user message).
      2. Send to LLM with tool schemas.
      3. If the model requests tool calls, execute them and append results.
      4. Repeat until finish_reason == "stop" or iteration limit.
      5. Render the final answer with Rich Markdown.
    """

    name: str = "Agent Mode"

    def __init__(
        self,
        chat_service: ChatService,
        tool_registry: ToolRegistry | None = None,
        workspace_root: str | None = None,
        safety_manager: Any = None,
        approval_provider: Any = None,
    ) -> None:
        self._chat_service = chat_service
        self._workspace_root = workspace_root or os.getcwd()

        from nakama_kun.safety.manager import SafetyManager
        from nakama_kun.safety.terminal import TerminalApprovalProvider

        self.safety_manager = safety_manager or SafetyManager(self._workspace_root)
        self.approval_provider = approval_provider or TerminalApprovalProvider()

        if tool_registry is not None:
            self._registry = tool_registry
        else:
            self._registry = build_default_registry(
                self._workspace_root,
                safety_manager=self.safety_manager,
                approval_provider=self.approval_provider,
            )

        self._router = ToolRouter(self._registry)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self) -> NavSignal:
        try:
            return asyncio.run(self._run_async())
        except KeyboardInterrupt:
            console.print("\n[yellow]Returning to menu...[/yellow]")
            return NavSignal.BACK

    # ------------------------------------------------------------------
    # Async implementation
    # ------------------------------------------------------------------

    async def _run_async(self) -> NavSignal:
        console.print()
        console.print(
            Panel(
                Text(
                    "nakama_kun Agent Mode\n"
                    "Describe your task, or type 'exit' to return.",
                    style=f"bold {Colours.AGENT}",
                    justify="center",
                ),
                border_style=Colours.AGENT,
                title="Agent Mode",
                subtitle=f"v{APP_VERSION}",
            )
        )

        from nakama_kun.mcp.manager import MCPManager

        mcp_manager = MCPManager(
            workspace_root=self._workspace_root,
            approval_provider=self.approval_provider,
        )

        try:
            await mcp_manager.connect_all()
            mcp_tools = await mcp_manager.get_tools()
            for tool in mcp_tools:
                self._registry.register(tool)

            tool_schemas = self._registry.all_schemas()
            console.print(
                f"[dim]Tools available: {', '.join(self._registry.names())}[/dim]\n"
            )

            # Persistent conversation history across tasks within this session
            history: list[Message] = []

            while True:
                try:
                    user_input = await questionary.text(
                        "Task:", style=_MENU_STYLE
                    ).ask_async()

                    if user_input is None:
                        console.print()
                        break

                    user_input = user_input.strip()
                    if not user_input:
                        continue
                    if user_input.lower() == "exit":
                        break

                    # Run the agentic loop for this user request
                    final_answer = await self._agent_loop(
                        user_input, history, tool_schemas
                    )

                    if final_answer:
                        console.print("\n[bold cyan]nakama_kun:[/bold cyan]")
                        console.print(
                            f"[bold dim]Model: "
                            f"{self._chat_service.provider.settings.openrouter_model}"
                            f"[/bold dim]\n"
                        )
                        with Live(Markdown(""), auto_refresh=False) as live:
                            live.update(Markdown(final_answer))
                            live.refresh()
                        console.print()

                        # Persist assistant reply in shared history
                        history.append(Message(role="assistant", content=final_answer))

                except APIKeyNotFoundError:
                    console.print("\n[bold red]API key not found.[/bold red]\n")
                except RateLimitError:
                    console.print(
                        "\n[bold red]Rate limit exceeded. Try again later.[/bold red]\n"
                    )
                except NetworkError:
                    console.print("\n[bold red]Unable to reach provider.[/bold red]\n")
                except InvalidModelError:
                    console.print(
                        "\n[bold red]Configured model unavailable.[/bold red]\n"
                    )
                except AIError as e:
                    console.print(f"\n[bold red]AI Error: {e}[/bold red]\n")
                except Exception as e:
                    console.print(f"\n[bold red]Unexpected error: {e}[/bold red]\n")

        finally:
            await mcp_manager.disconnect_all()

        return NavSignal.BACK

    async def _agent_loop(
        self,
        user_task: str,
        history: list[Message],
        tool_schemas: list[dict[str, Any]],
    ) -> str:
        """Run the task using LangGraph orchestration workflow."""
        import uuid

        from loguru import logger

        from nakama_kun.ai.services.planner_service import PlannerService
        from nakama_kun.memory import get_memory_repository
        from nakama_kun.orchestration.nodes import RESEARCH_THRESHOLD
        from nakama_kun.orchestration.workflow import build_agent_graph

        task_id = str(uuid.uuid4())
        repo = get_memory_repository()

        # Log task execution start
        try:
            repo.save_task_metadata(task_id, user_task, "running")
        except Exception as e:
            logger.warning(f"Failed to log task execution start: {e}")

        # Initialize planner and build the orchestrator graph
        planner_service = PlannerService(self._chat_service)
        graph = build_agent_graph(
            chat_service=self._chat_service,
            planner_service=planner_service,
            tool_registry=self._registry,
            tool_router=self._router,
        ).compile()

        # Retrieve matching codebase chunks for initial context
        from nakama_kun.rag import get_retriever
        initial_messages = list(history)
        retriever = get_retriever(self._workspace_root)
        if retriever is not None:
            rag_context = retriever.retrieve_formatted_context(user_task)
            if rag_context:
                initial_messages.append(Message(role="system", content=rag_context))

        # Build initial workflow state
        initial_state: dict[str, Any] = {
            "goal": user_task,
            "plan": None,
            "required_artifacts": [],
            "created_artifacts": [],
            "missing_artifacts": [],
            "research_budget_remaining": RESEARCH_THRESHOLD,
            "delivery_mode": False,
            "retry_memory": {
                "completed_actions": [],
                "failed_actions": [],
                "failed_validations": [],
                "reviewer_feedback": [],
                "failed_attempt_signatures": [],
            },
            "messages": initial_messages,
            "tool_results": [],
            "reviewer_feedback": None,
            "retry_count": 0,
            "final_response": None,
            "status": "planning",
            "goal_satisfied": False,
            "active_agent": "",
            "agent_outputs": {},
            "agent_metrics": {},
            "retrieval_package": None,
            "test_report": None,
        }

        # Keep history in-sync
        history.append(Message(role="user", content=user_task))

        try:
            final_state = await graph.ainvoke(initial_state)
            final_answer = final_state.get("final_response") or "Task completed."

            # Log task completion success
            try:
                repo.save_task_metadata(task_id, user_task, "done")
            except Exception as e:
                logger.warning(f"Failed to log task success: {e}")

            return final_answer

        except Exception as exc:
            # Log task execution failure
            try:
                repo.save_task_metadata(task_id, user_task, "failed")
            except Exception as e:
                logger.warning(f"Failed to log task failure: {e}")
            raise exc

    async def _execute_tool_call(self, tc: ToolCall) -> str:
        """Dispatch a single ``ToolCall`` and return the result as a string."""
        import json

        from nakama_kun.tools.exceptions import ToolError

        name: str = tc.function.get("name", "")
        arguments = tc.function.get("arguments", {})

        console.print(
            f"[dim]  → Tool call: [bold]{name}[/bold] "
            f"args={json.dumps(arguments, ensure_ascii=False)[:120]}[/dim]"
        )

        try:
            result = await self._router.dispatch(name, arguments)
        except ToolError as exc:
            console.print(f"[yellow]  ✗ Tool '{name}' error: {exc}[/yellow]")
            return f"ERROR: {exc}"
        except Exception as exc:
            console.print(f"[red]  ✗ Tool '{name}' unexpected error: {exc}[/red]")
            return f"ERROR: {exc}"

        status = "✓" if result.success else "✗"
        console.print(
            f"[dim]  {status} Tool '{name}' "
            f"({'ok' if result.success else 'failed'})[/dim]"
        )
        return result.to_content()
