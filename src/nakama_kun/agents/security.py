from __future__ import annotations

import re
import os
import json
from typing import Any
from loguru import logger

from nakama_kun.agents.base import BaseAgent
from nakama_kun.agents.models import SecurityReport, parse_security_report
from nakama_kun.ai.models.message import Message


class SecurityAgent(BaseAgent):
    """Security Agent is responsible for secret detection, unsafe command scanning, and code/dependency security reviews."""

    def __init__(self, chat_service: Any) -> None:
        from nakama_kun.agents.prompts import SECURITY_AGENT_PROMPT
        super().__init__(
            name="SecurityAgent",
            role="security",
            system_prompt=SECURITY_AGENT_PROMPT,
            chat_service=chat_service,
        )

    async def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        logger.info("[SecurityAgent] Starting security verification and review...")
        goal = state["goal"]

        # Gather context
        proposals = state.get("coder_proposals") or []
        created_artifacts = state.get("created_artifacts") or []
        tool_results = state.get("tool_results") or []

        # 1. Rule-Based Deterministic Scan
        det_warnings = []
        det_vulnerabilities = []
        det_blocked_actions = []
        det_remediations = []

        # Secret detection pattern (simple checks)
        secret_keys_regex = re.compile(
            r"(api[_-]?key|password|secret|passwd|token|private[_-]?key|credential|auth[_-]?token|signature)\s*[:=]\s*['\"][a-zA-Z0-9_\-\.\:\/]{8,}['\"]",
            re.IGNORECASE
        )
        base64_regex = re.compile(r"['\"](?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?['\"]")

        # Unsafe command detection pattern
        unsafe_cmd_regex = re.compile(
            r"\b(rm\s+-rf\s+/|chmod\s+777|curl\s+.*\s*\|\s*(bash|sh)|wget\s+.*\s*\|\s*(bash|sh)|sudo\s+rm|mkfs|dd\s+if=)\b",
            re.IGNORECASE
        )

        # Scan code proposals
        for prop in proposals:
            path = prop.get("path") or ""
            content = prop.get("content") or ""

            # Secret check
            if secret_keys_regex.search(content):
                det_vulnerabilities.append(f"Hardcoded secret/key pattern detected in proposed file '{path}'.")
                det_remediations.append(f"Remove hardcoded credentials from '{path}' and use environment variables.")

            # Dependency additions check
            if any(name in path for name in ("requirements.txt", "pyproject.toml", "setup.py")):
                det_warnings.append(f"Dependency configuration modified in '{path}'. Validate package hashes and sources.")
                det_remediations.append(f"Run dependency audit checks for any new packages introduced in '{path}'.")

        # Scan executed shell commands
        for tr in tool_results:
            tool_name = tr.get("tool") or ""
            args = tr.get("arguments") or {}
            success = tr.get("success", False)

            if tool_name == "run_command":
                cmd = ""
                if isinstance(args, dict):
                    cmd = args.get("CommandLine") or ""
                elif isinstance(args, str):
                    cmd = args

                if cmd and unsafe_cmd_regex.search(cmd):
                    det_blocked_actions.append(f"Unsafe shell command block triggered for: '{cmd}'.")
                    det_remediations.append(f"Avoid executing destructive commands like '{cmd}' directly. Refactor the implementation.")

        # 2. LLM-Based Security Review
        user_prompt = (
            f"Goal: {goal}\n\n"
            f"### Proposed Code Modifications:\n"
        )
        for p in proposals:
            user_prompt += f"File: {p.get('path')}\nContent:\n{p.get('content')}\n---\n"

        user_prompt += "\n### Executed Commands and Actions:\n"
        for tr in tool_results:
            user_prompt += f"Tool: {tr.get('tool')} (Success: {tr.get('success')}) Args: {tr.get('arguments')}\n"

        messages = [
            Message(role="system", content=self.system_prompt),
            Message(role="user", content=user_prompt),
        ]

        try:
            response = await self.chat_service.provider.generate(messages)
            raw_text = response.content or ""
            report = parse_security_report(raw_text)
        except Exception as e:
            logger.warning(f"[SecurityAgent] LLM security generation failed: {e}")
            report = None

        if not report:
            logger.warning("[SecurityAgent] Falling back to default empty SecurityReport.")
            report = SecurityReport(
                warnings=[],
                vulnerabilities=[],
                blocked_actions=[],
                remediation_suggestions=[],
            )

        # Merge deterministic scan results with LLM report
        merged_warnings = sorted(list(set(report.warnings + det_warnings)))
        merged_vulns = sorted(list(set(report.vulnerabilities + det_vulnerabilities)))
        merged_blocked = sorted(list(set(report.blocked_actions + det_blocked_actions)))
        merged_remediations = sorted(list(set(report.remediation_suggestions + det_remediations)))

        final_report = SecurityReport(
            warnings=merged_warnings,
            vulnerabilities=merged_vulns,
            blocked_actions=merged_blocked,
            remediation_suggestions=merged_remediations
        )

        history_entry = {
            "agent": self.name,
            "thought": f"Completed security review. Found {len(merged_vulns)} vulnerabilities and {len(merged_blocked)} blocked actions.",
            "handoff": final_report.model_dump(),
        }

        # Conforming to contract: return structured outputs only
        return {
            "security_report": final_report,
            "agent_history": [history_entry],
            "messages": [
                Message(role="assistant", content=f"SecurityAgent verification completed. Found {len(merged_vulns)} vulnerability warning(s) and {len(merged_blocked)} blocked action(s).")
            ],
            "status": "verifying",
        }
