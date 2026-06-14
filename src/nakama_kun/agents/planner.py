from __future__ import annotations

import json
from typing import Any

from loguru import logger

from nakama_kun.agents.base import BaseAgent
from nakama_kun.agents.prompts import PLANNER_AGENT_PROMPT
from nakama_kun.ai.models.message import Message
from nakama_kun.ai.models.plan import parse_plan
from nakama_kun.rag import get_retriever
from nakama_kun.workspace.context import WorkspaceContextBuilder


class PlannerAgent(BaseAgent):
    """Planner Agent decomposes goals into discrete tasks and file targets."""

    def __init__(self, chat_service: Any, tool_registry: Any = None) -> None:
        from nakama_kun.agents.prompts import PLANNER_AGENT_PROMPT
        if tool_registry is None:
            from nakama_kun.tools import build_default_registry
            reg = build_default_registry()
        else:
            reg = tool_registry

        super().__init__(
            name="PlannerAgent",
            role="planner",
            system_prompt=PLANNER_AGENT_PROMPT,
            chat_service=chat_service,
            tools=reg.all_schemas() if reg else [],
        )
        self.tool_registry = reg
        self.memory["successful_plans"] = []

    @property
    def successful_plans(self) -> list[Any]:
        """Returns the history of plans that were successfully executed/approved."""
        return self.memory.get("successful_plans", [])

    def _build_tool_capability_summary(self) -> str:
        summary_lines = ["### Available Tools and Capability Summary\n"]
        from nakama_kun.tools.discovery import ToolDiscoveryService
        discovery = ToolDiscoveryService(self.tool_registry)

        local_tools = []
        mcp_tools = []

        for tool in discovery.list_available_tools():
            from nakama_kun.tools.adapters import MCPToolAdapter
            if isinstance(tool, MCPToolAdapter):
                mcp_tools.append(tool)
            else:
                local_tools.append(tool)

        summary_lines.append("#### Local Tools (Workspace & System)")
        for tool in local_tools:
            summary_lines.append(f"- **{tool.name}**:")
            summary_lines.append(f"  * Purpose: {tool.description}")
            summary_lines.append(f"  * Permissions: {', '.join(tool.permissions) if tool.permissions else 'none'}")
            summary_lines.append(f"  * Typical Use Cases: {tool.usage_description}")

        summary_lines.append("\n#### External MCP Tools (External Systems)")
        for tool in mcp_tools:
            server_name = tool.mcp_tool.server_name if hasattr(tool, "mcp_tool") else "unknown"
            summary_lines.append(f"- **{tool.name}**:")
            summary_lines.append(f"  * Purpose: {tool.description}")
            summary_lines.append(f"  * Permissions: {', '.join(tool.permissions) if tool.permissions else 'none'}")
            summary_lines.append(f"  * Server: {server_name}")
            summary_lines.append(f"  * Typical Use Cases: {tool.usage_description}")

        return "\n".join(summary_lines)

    async def plan(self, state: dict[str, Any]) -> dict[str, Any]:
        logger.info("[PlannerAgent] Starting planning task...")
        goal = state.get("goal", "")
        feedback = state.get("reviewer_feedback")
        retry_count = state.get("retry_count", 0)

        # 1. Retrieve codebase context (RAG) and workspace summary
        workspace_context = ""
        try:
            workspace_context = WorkspaceContextBuilder().build_summary(goal)
        except Exception as e:
            logger.warning(f"Failed to build workspace context summary: {e}")

        rag_context = ""
        retriever = get_retriever()
        if retriever is not None:
            try:
                rag_context = retriever.retrieve_planner_context(goal)
            except Exception as e:
                logger.warning(f"Failed to retrieve RAG context: {e}")

        # Retrieve past experiences semantically
        experience_context = ""
        hints = []
        bundle = None
        try:
            from nakama_kun.config.memory import MemorySettings
            from nakama_kun.memory.sqlite_store import SQLiteMemoryStore
            from nakama_kun.memory.retriever import ExperienceRetriever
            from nakama_kun.memory.experience_planner import ExperienceAwarePlanner

            settings = MemorySettings()
            if settings.memory_enabled:
                store = SQLiteMemoryStore(settings.memory_db_path)
                experience_retriever = ExperienceRetriever(store, workspace_root=state.get("workspace_root"))
                bundle = experience_retriever.retrieve_experience(goal)
                exp_planner = ExperienceAwarePlanner()
                experience_context = exp_planner.build_prompt_section(bundle)
                hints = exp_planner.build_failure_prevention_hints(bundle)
        except Exception as e:
            logger.warning(f"Failed to retrieve experience context: {e}")

        # Build full system prompt
        system_prompt = PLANNER_AGENT_PROMPT

        # Inject Tool Capability Summary
        tool_summary = self._build_tool_capability_summary()
        if tool_summary:
            system_prompt += f"\n\n{tool_summary}"

        if workspace_context:
            system_prompt += f"\n\n### Workspace Context\n{workspace_context}"
        if rag_context:
            system_prompt += f"\n\n{rag_context}"
        if experience_context:
            system_prompt += f"\n\n### Past Experiences\n{experience_context}"
        if hints:
            hints_block = "\n".join(f"* {h}" for h in hints)
            system_prompt += f"\n\n### Failure Prevention Guidance\n{hints_block}"

        # 2. Build user prompt/refinement context
        if feedback:
            logger.info(f"[PlannerAgent] Refining plan based on reviewer feedback (retry {retry_count})...")

            # Extract completed and failed actions
            completed_actions = []
            previous_failures = []
            for r in state.get("tool_results", []):
                tool_name = r.get("tool", "")
                arguments = r.get("arguments", {})
                success = r.get("success", False)
                if success:
                    completed_actions.append(f"- Tool '{tool_name}' succeeded with args: {json.dumps(arguments)}")
                else:
                    error = r.get("error") or r.get("content") or "unknown error"
                    content_snippet = error[:200] + "..." if len(error) > 200 else error
                    previous_failures.append(
                        f"- Tool '{tool_name}' failed with args: {json.dumps(arguments)}\n"
                        f"  Output/Error: {content_snippet}"
                    )

            refinement_prompt = [
                "Your previous plan failed to meet requirements. Please refine it.",
                f"Original Goal: {goal}",
                f"Reviewer Feedback: {feedback}",
                "\n### Execution History",
                "Completed Actions:",
                "\n".join(completed_actions) if completed_actions else "(none)",
                "\nPrevious Failures:",
                "\n".join(previous_failures) if previous_failures else "(none)",
                "\nPlease refine the plan to address the feedback and failures."
            ]
            user_prompt = "\n".join(refinement_prompt)
        else:
            user_prompt = f"Goal: {goal}"

        # 3. Call LLM
        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt)
        ]
        response = await self.chat_service.provider.generate(messages)
        raw_text = response.content or ""

        # 4. Parse Plan
        plan = parse_plan(raw_text)
        if plan and bundle is not None:
            try:
                from nakama_kun.memory.experience_planner import ExperienceAwarePlanner
                exp_planner = ExperienceAwarePlanner()
                plan.memory_insights = exp_planner.build_memory_insights(bundle)
            except Exception as e:
                logger.warning(f"Failed to attach memory insights to plan: {e}")

        # 5. Log decisions and append history
        thought = f"Decomposed goal. Success: {plan is not None}."
        if feedback:
            thought = f"Refined plan based on feedback. Success: {plan is not None}."

        log_entry = {
            "agent": "PlannerAgent",
            "thought": thought,
            "handoff": plan.model_dump() if plan else {"raw_response": raw_text},
        }

        history = list(state.get("agent_history", []))
        history.append(log_entry)

        # Prepare outputs matching make_planner_node expectations
        planned_artifacts = plan.required_artifacts if plan else []
        required_artifacts = planned_artifacts or state.get("required_artifacts", [])
        created_artifacts = list(state.get("created_artifacts", [])) if feedback else []
        missing_artifacts = [a for a in required_artifacts if a not in created_artifacts]

        return {
            "plan": plan,
            "required_artifacts": required_artifacts,
            "created_artifacts": created_artifacts,
            "missing_artifacts": missing_artifacts,
            "agent_history": history,
            "status": "executing",
            "messages": [
                Message(role="assistant", content=f"Planner proposed Plan:\n{raw_text}")
            ],
        }
