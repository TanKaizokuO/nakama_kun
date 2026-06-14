from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

from nakama_kun.ai.services.chat_service import ChatService


class BaseAgent(ABC):
    """Abstract base class for specialized agents in Nakama-kun."""

    def __init__(
        self,
        name: str,
        role: str,
        system_prompt: str,
        chat_service: ChatService,
        tools: list[Any] | None = None,
        memory: dict[str, Any] | None = None,
    ) -> None:
        self._name = name
        self._role = role
        self._system_prompt = system_prompt
        self.chat_service = chat_service
        self._tools = tools or []
        self._memory = memory or {}

    @property
    def name(self) -> str:
        """The agent's name."""
        return self._name

    @property
    def role(self) -> str:
        """The agent's role (e.g. planner, coder, verifier, reviewer)."""
        return self._role

    @property
    def system_prompt(self) -> str:
        """The agent's system prompt."""
        return self._system_prompt

    @property
    def tools(self) -> list[Any]:
        """List of tools available to this agent."""
        return self._tools

    @property
    def memory(self) -> dict[str, Any]:
        """The agent's memory dict/view."""
        return self._memory

    async def plan(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute planning logic."""
        raise NotImplementedError(f"Agent {self.name} does not implement plan().")

    async def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute action/tool execution logic."""
        raise NotImplementedError(f"Agent {self.name} does not implement execute().")

    async def review(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute review/QA logic."""
        raise NotImplementedError(f"Agent {self.name} does not implement review().")

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute the agent's default task, routing to plan, execute, or review based on role,
        and tracks active_agent, agent_outputs, agent_metrics, and updates memory views.
        """
        start_time = time.time()
        
        # 1. Execute agent logic based on role
        if self.role == "planner":
            updates = await self.plan(state)
        elif self.role == "coder":
            updates = await self.execute(state)
        elif self.role == "verifier":
            updates = await self.execute(state)
        elif self.role == "reviewer":
            updates = await self.review(state)
        else:
            raise ValueError(f"Unknown agent role: {self.role}")

        duration = time.time() - start_time

        # 2. Track active_agent
        updates["active_agent"] = self.name

        # 3. Track agent_outputs
        outputs = dict(state.get("agent_outputs") or {})
        if self.role == "planner":
            outputs[self.name] = updates.get("plan")
        elif self.role == "coder":
            # Store coder proposals or tool outputs
            outputs[self.name] = {
                "proposals": updates.get("coder_proposals"),
                "tool_results": updates.get("tool_results"),
            }
        elif self.role == "verifier":
            outputs[self.name] = updates.get("verification_report")
        elif self.role == "reviewer":
            outputs[self.name] = {
                "feedback": updates.get("reviewer_feedback"),
                "route": updates.get("reviewer_route"),
            }
        updates["agent_outputs"] = outputs

        # 4. Track agent_metrics
        metrics = dict(state.get("agent_metrics") or {})
        metrics[self.name] = {
            "duration_seconds": duration,
            "status": updates.get("status") or state.get("status"),
        }
        updates["agent_metrics"] = metrics

        # 5. Populate and synchronize memory views
        history = state.get("agent_history", []) + (updates.get("agent_history") or [])
        if self.role == "planner":
            plans = []
            for h in history:
                if h.get("agent") in ("PlannerAgent", self.name):
                    handoff = h.get("handoff")
                    if isinstance(handoff, dict) and "goal_summary" in handoff:
                        plans.append(handoff)
            self._memory["successful_plans"] = plans
        elif self.role == "coder":
            self._memory["implementation_history"] = [
                h for h in history
                if h.get("agent") in ("CoderAgent", "ExecutorAgent", self.name)
            ]
        elif self.role == "verifier":
            self._memory["validation_history"] = [
                h for h in history
                if h.get("agent") in ("VerifierAgent", self.name)
            ]
        elif self.role == "reviewer":
            self._memory["review_history"] = [
                h.get("handoff") for h in history
                if h.get("agent") in ("ReviewerAgent", self.name)
            ]

        return updates
