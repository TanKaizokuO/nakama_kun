from __future__ import annotations

from typing import Any
from loguru import logger

from nakama_kun.agents.base import BaseAgent
from nakama_kun.agents.prompts import VERIFIER_AGENT_PROMPT
from nakama_kun.ai.models.message import Message
from nakama_kun.orchestration.verification import VerificationLayer
from nakama_kun.orchestration.evidence import build_evidence_store


def _paths_match(expected: str, actual: str) -> bool:
    from pathlib import Path
    expected_path = Path(expected)
    actual_path = Path(actual)
    return (
        actual == expected
        or actual.endswith(expected)
        or actual_path.name == expected_path.name
    )


def _missing_required_artifacts(
    required_artifacts: list[str],
    created_artifacts: list[str],
) -> list[str]:
    missing = []
    for required in required_artifacts:
        if not any(_paths_match(required, created) for created in created_artifacts):
            missing.append(required)
    return missing


class VerifierAgent(BaseAgent):
    """Verifier Agent performs workspace verification, compiles reports, and runs test suites."""

    def __init__(self, workspace_root: str | None = None, chat_service: Any = None) -> None:
        super().__init__(
            name="VerifierAgent",
            role="verifier",
            system_prompt=VERIFIER_AGENT_PROMPT,
            chat_service=chat_service,
        )
        self.workspace_root = workspace_root
        self.layer = VerificationLayer(workspace_root=workspace_root)
        self.memory["validation_history"] = []

    @property
    def validation_history(self) -> list[Any]:
        """Returns the history of validations performed by the verifier."""
        return self.memory.get("validation_history", [])

    async def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        logger.info("[VerifierAgent] Running workspace verification and testing...")
        
        # 1. Run Verification Layer and build evidence store
        report = self.layer.run(state)
        evidence_store = build_evidence_store(state, report, self.workspace_root)
        
        # 2. Extract verified artifacts
        verified_artifacts = [
            artifact.path
            for artifact in [*report.files_created, *report.files_modified]
            if artifact.exists
        ]
        created_artifacts = list(state.get("created_artifacts", []))
        for artifact in verified_artifacts:
            if artifact not in created_artifacts:
                created_artifacts.append(artifact)
                
        missing_artifacts = _missing_required_artifacts(
            state.get("required_artifacts", []),
            created_artifacts,
        )
        
        # 3. Log to agent history
        log_entry = {
            "agent": "VerifierAgent",
            "thought": f"Verification completed: {report.summary}",
            "handoff": {
                "summary": report.summary,
                "files_created": [f.path for f in report.files_created],
                "files_modified": [f.path for f in report.files_modified],
                "tests_total": len(report.command_results),
            }
        }
        history = list(state.get("agent_history", []))
        history.append(log_entry)
        
        return {
            "verification_report": report,
            "evidence_store": evidence_store,
            "created_artifacts": created_artifacts,
            "missing_artifacts": missing_artifacts,
            "status": "reviewing",
            "agent_history": history,
            "messages": [
                Message(role="assistant", content=f"Verifier completed verification: {report.summary}")
            ],
        }
