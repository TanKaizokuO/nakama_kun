from __future__ import annotations

import json
from typing import Any

from loguru import logger

from nakama_kun.agents.base import BaseAgent
from nakama_kun.agents.models import (
    SupervisorDecision,
    TaskDelegation,
    parse_supervisor_decision,
)
from nakama_kun.agents.registry import AgentCapabilityRegistry
from nakama_kun.ai.models.message import Message


class SupervisorAgent(BaseAgent):
    """Supervisor Agent that decomposes goals and schedules agents dynamically."""

    def __init__(self, chat_service: Any) -> None:
        from nakama_kun.agents.prompts import SUPERVISOR_AGENT_PROMPT
        super().__init__(
            name="SupervisorAgent",
            role="supervisor",
            system_prompt=SUPERVISOR_AGENT_PROMPT,
            chat_service=chat_service,
        )
        self.registry = AgentCapabilityRegistry()

    async def plan(self, state: dict[str, Any]) -> dict[str, Any]:
        logger.info("[SupervisorAgent] Scheduling and managing task execution...")
        goal = state.get("goal", "")
        history = state.get("agent_history") or []
        metrics = state.get("agent_metrics") or {}
        active_agent = state.get("active_agent", "")

        # 1. Update Telemetry
        telemetry = dict(state.get("supervisor_telemetry") or {})
        utilization = dict(telemetry.get("agent_utilization") or {})
        latencies = list(telemetry.get("task_latency") or [])
        delegation_history = list(telemetry.get("delegation_history") or [])
        failure_rates = dict(telemetry.get("failure_rates") or {})

        # Track total runs vs failed runs for failure rate calculation
        run_counts = {}
        fail_counts = {}

        # Scan agent history to rebuild run statistics and failures
        for h in history:
            agent_name = h.get("agent")
            if not agent_name or agent_name == "SupervisorAgent":
                continue

            run_counts[agent_name] = run_counts.get(agent_name, 0) + 1

            # Determine if this run was a failure
            is_fail = False
            handoff = h.get("handoff")
            if isinstance(handoff, dict):
                # Reviewer rejection
                if handoff.get("approved") is False:
                    is_fail = True
                # Security vulnerabilities/blocked actions
                if handoff.get("bugs") or handoff.get("risks"):
                    is_fail = True

            # Check test failures
            test_rep = state.get("test_report")
            if agent_name == "TestAgent" and test_rep:
                if (test_rep.failed or 0) > 0 or (test_rep.errors or 0) > 0:
                    is_fail = True

            # Check security vulnerabilities
            sec_rep = state.get("security_report")
            if agent_name == "SecurityAgent" and sec_rep:
                if (sec_rep.vulnerabilities or []) or (sec_rep.blocked_actions or []):
                    is_fail = True

            if is_fail:
                fail_counts[agent_name] = fail_counts.get(agent_name, 0) + 1

        # Re-populate utilization
        for name, count in run_counts.items():
            utilization[name] = count

        # Compute failure rates
        for name, runs in run_counts.items():
            fails = fail_counts.get(name, 0)
            failure_rates[name] = fails / runs

        # If a new active_agent just ran, log its latency
        if active_agent and active_agent in metrics:
            agent_dur = metrics[active_agent].get("duration_seconds", 0.0)
            latencies.append({
                "agent": active_agent,
                "duration_seconds": agent_dur,
            })

        # Update telemetry object
        telemetry["agent_utilization"] = utilization
        telemetry["task_latency"] = latencies
        telemetry["failure_rates"] = failure_rates

        # 2. Formulate LLM prompts
        agent_profiles = [
            f"- {a.name} (role: {a.role}): capabilities={a.capabilities}, tools={a.tool_access}"
            for a in self.registry.list_agents()
        ]
        agent_capabilities_str = "\n".join(agent_profiles)

        current_delegations = state.get("delegations") or []
        delegations_str = json.dumps([d if isinstance(d, dict) else d.model_dump() for d in current_delegations], indent=2)

        # Recent outputs context
        recent_outputs = {}
        if state.get("retrieval_package"):
            recent_outputs["RetrieverAgent"] = "RetrievalPackage available with " + str(len(state["retrieval_package"].retrieved_files)) + " files."
        if state.get("coder_proposals"):
            recent_outputs["CoderAgent"] = "CoderProposals available modifying: " + str([p.get("path") for p in state["coder_proposals"]])
        if state.get("test_report"):
            t_rep = state["test_report"]
            recent_outputs["TestAgent"] = f"Tests: passed={t_rep.passed}, failed={t_rep.failed}, skipped={t_rep.skipped}, errors={t_rep.errors}"
        if state.get("security_report"):
            s_rep = state["security_report"]
            recent_outputs["SecurityAgent"] = f"Security: warnings={len(s_rep.warnings)}, vulnerabilities={len(s_rep.vulnerabilities)}, blocked={len(s_rep.blocked_actions)}"
        if state.get("verification_report"):
            recent_outputs["VerifierAgent"] = "VerificationReport exists."
        if state.get("reviewer_feedback"):
            recent_outputs["ReviewerAgent"] = f"Rejection Feedback: {state['reviewer_feedback']}"

        recent_outputs_str = json.dumps(recent_outputs, indent=2)
        history_log_str = json.dumps([{
            "agent": h.get("agent"),
            "thought": h.get("thought"),
            "handoff": h.get("handoff")
        } for h in history], indent=2)

        user_prompt = f"""User Goal: {goal}

Available Specialized Agents:
{agent_capabilities_str}

Current Task Delegations:
{delegations_str}

Recent Agent Outputs:
{recent_outputs_str}

Execution History Log:
{history_log_str}

Telemetry State:
{json.dumps(telemetry, indent=2)}

Please provide your rationale, task delegations updates, and specify the next agent(s) to execute.
"""

        messages = [
            Message(role="system", content=self.system_prompt),
            Message(role="user", content=user_prompt),
        ]

        # 3. Call LLM
        decision = None
        try:
            response = await self.chat_service.provider.generate(messages)
            decision = parse_supervisor_decision(response.content or "")
        except Exception as e:
            logger.error(f"[SupervisorAgent] LLM generation/parsing error: {e}")

        # 4. Fallback Logic
        if not decision:
            logger.warning("[SupervisorAgent] Falling back to deterministic sequential scheduling.")
            decision = self._get_fallback_decision(state, current_delegations)

        # Update delegation history
        for agent_name in decision.next_agents:
            delegation_history.append({
                "agent": agent_name,
                "timestamp": len(delegation_history),
            })
        telemetry["delegation_history"] = delegation_history

        # Log reasoning to history
        thought = f"Scheduled: {decision.next_agents}. Rationale: {decision.rationale}"
        history_entry = {
            "agent": self.name,
            "thought": thought,
            "handoff": {
                "next_agents": decision.next_agents,
                "status": decision.status,
                "rationale": decision.rationale,
            }
        }

        # Convert TaskDelegation list to dicts for state compatibility
        serializable_delegations = [
            d if isinstance(d, dict) else d.model_dump()
            for d in decision.delegations
        ]

        return {
            "status": decision.status,
            "delegations": serializable_delegations,
            "supervisor_telemetry": telemetry,
            "agent_history": [history_entry],
            "messages": [Message(role="assistant", content=f"Supervisor Decision:\n{thought}")],
            # If done, final routing value is resolved
            "reviewer_route": None,
        }

    def _get_fallback_decision(
        self,
        state: dict[str, Any],
        current_delegations: list[Any],
    ) -> SupervisorDecision:
        """Sequential fallback scheduler matching the classic linear pipelines."""
        active_agent = state.get("active_agent", "")
        task_type = state.get("task_type") or "MODIFICATION"
        reviewer_feedback = state.get("reviewer_feedback")

        next_agents = []
        status = "executing"
        rationale = "Sequential pipeline fallback scheduling due to parsing errors."

        # Map active agent to the next step
        if not active_agent:
            next_agents = ["RetrieverAgent"]
        elif active_agent == "RetrieverAgent":
            if task_type == "RETRIEVAL":
                next_agents = ["ReviewerAgent"]
            else:
                next_agents = ["CoderAgent"]
        elif active_agent == "CoderAgent":
            next_agents = ["TestAgent"]
        elif active_agent == "TestAgent":
            next_agents = ["SecurityAgent"]
        elif active_agent == "SecurityAgent":
            next_agents = ["VerifierAgent"]
        elif active_agent == "VerifierAgent":
            next_agents = ["ReviewerAgent"]
        elif active_agent == "ReviewerAgent":
            if not reviewer_feedback:
                next_agents = ["final_response"]
                status = "done"
            else:
                next_agents = ["CoderAgent"]  # rejection loop back to coder
        else:
            next_agents = ["final_response"]
            status = "done"

        # Construct/maintain task delegations
        delegations = []
        for d in current_delegations:
            if isinstance(d, dict):
                delegations.append(TaskDelegation.model_validate(d))
            else:
                delegations.append(d)

        # Append new delegation for the scheduled fallback agents
        for na in next_agents:
            if na != "final_response" and not any(d.assigned_agent == na and d.status == "pending" for d in delegations):
                delegations.append(TaskDelegation(
                    task=f"Fallback execution of {na}",
                    assigned_agent=na,
                    priority=1,
                    dependencies=[],
                    status="pending",
                ))

        # Update previous fallback tasks to completed
        if active_agent:
            for d in delegations:
                if d.assigned_agent == active_agent:
                    d.status = "completed"

        return SupervisorDecision(
            rationale=rationale,
            next_agents=next_agents,
            delegations=delegations,
            status=status,
        )
