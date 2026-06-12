from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FileChangeProposal:
    """Represents a proposed change to a file before it is applied."""

    file_path: Path  # Resolved path within workspace
    change_type: str  # 'create', 'update', or 'delete'
    original_content: str | None  # Content before change, or None if new file
    proposed_content: str | None  # Target content, or None if deleting
    diff_text: str  # Unified diff representation for user inspection


class ApprovalProvider(ABC):
    """Abstract interface to ask for approval of proposed workspace changes."""

    @abstractmethod
    async def request_approval(self, proposal: FileChangeProposal) -> bool:
        """Asks the user or external router to approve the proposal.

        Returns True if approved, False if rejected.
        """
        pass


class AutoApprovalProvider(ApprovalProvider):
    """Automatically approves or rejects all proposals (useful for testing)."""

    def __init__(self, approve: bool = True) -> None:
        self.approve = approve

    async def request_approval(self, proposal: FileChangeProposal) -> bool:
        return self.approve
