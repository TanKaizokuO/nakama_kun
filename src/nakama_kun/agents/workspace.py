from __future__ import annotations

from typing import Any


class AgentWorkspace:
    """A shared read-only context containing repository context, retrieval results, evidence, and reports."""

    def __init__(self, state: dict[str, Any]) -> None:
        self._repository_context = state.get("workspace_context") or ""
        self._retrieval_package = state.get("retrieval_package")
        self._evidence_store = state.get("evidence_store")
        self._reports = {
            "plan": state.get("plan"),
            "coder_proposals": state.get("coder_proposals") or [],
            "test_report": state.get("test_report"),
            "verification_report": state.get("verification_report"),
            "security_report": state.get("security_report"),
        }

    @property
    def repository_context(self) -> str:
        """Shared read-only repository/workspace context."""
        return self._repository_context

    @property
    def retrieval_results(self) -> Any:
        """Shared read-only retrieval results."""
        return self._retrieval_package

    @property
    def evidence(self) -> Any:
        """Shared read-only evidence store."""
        return self._evidence_store

    @property
    def reports(self) -> dict[str, Any]:
        """Shared read-only dictionary of agent reports."""
        return self._reports
