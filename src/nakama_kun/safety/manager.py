from __future__ import annotations

import difflib
import os
from pathlib import Path

from nakama_kun.safety.models import ApprovalProvider, FileChangeProposal
from nakama_kun.tools.safety import assert_within_workspace


class SafetyManager:
    """Manages diff generation, path escaping guardrails, approvals, and rollback logs."""

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self.workspace_root = Path(workspace_root or os.getcwd()).resolve()
        self.history: list[FileChangeProposal] = []

    def propose_change(
        self, path: str | Path, proposed_content: str | None, change_type: str | None = None
    ) -> FileChangeProposal:
        """Resolve the path, read current file content, generate a diff, and return a proposal."""
        # 1. Resolve and check path safety
        safe_path = assert_within_workspace(path, self.workspace_root)
        rel_path = safe_path.relative_to(self.workspace_root)

        # 2. Retrieve original content
        original_content: str | None = None
        if safe_path.exists():
            try:
                original_content = safe_path.read_text(encoding="utf-8")
            except OSError:
                original_content = None

        # 3. Determine change type if not explicitly supplied
        if change_type is None:
            if proposed_content is None:
                change_type = "delete"
            elif original_content is None:
                change_type = "create"
            else:
                change_type = "update"

        # 4. Generate Unified Diff using difflib
        diff_text = self._generate_diff(str(rel_path), original_content, proposed_content)

        return FileChangeProposal(
            file_path=safe_path,
            change_type=change_type,
            original_content=original_content,
            proposed_content=proposed_content,
            diff_text=diff_text,
        )

    def apply_proposal(
        self, proposal: FileChangeProposal, provider: ApprovalProvider
    ) -> bool:
        """Submit the proposal to the provider. If approved, make changes and record rollback info."""
        if not provider.request_approval(proposal):
            return False

        # Apply change
        if proposal.change_type in ("create", "update"):
            if proposal.proposed_content is None:
                raise ValueError("Proposed content is required for creations/updates.")
            proposal.file_path.parent.mkdir(parents=True, exist_ok=True)
            proposal.file_path.write_text(proposal.proposed_content, encoding="utf-8")
        elif proposal.change_type == "delete":
            if proposal.file_path.exists():
                proposal.file_path.unlink()

        # Log to rollback history
        self.history.append(proposal)
        return True

    def rollback_last(self) -> bool:
        """Rolls back the last applied file change proposal in history.

        Returns True if successful, False if history is empty.
        """
        if not self.history:
            return False

        proposal = self.history.pop()

        if proposal.change_type == "create":
            # Created files are deleted on rollback
            if proposal.file_path.exists():
                proposal.file_path.unlink()
        elif proposal.change_type in ("update", "delete"):
            # Updated or deleted files are restored to their original content
            if proposal.original_content is not None:
                proposal.file_path.parent.mkdir(parents=True, exist_ok=True)
                proposal.file_path.write_text(proposal.original_content, encoding="utf-8")
            elif proposal.file_path.exists():
                # If it didn't exist before (should not happen for update/delete), delete it
                proposal.file_path.unlink()

        return True

    def rollback_all(self) -> int:
        """Rolls back all changes in the history stack. Returns number of rolled back items."""
        count = 0
        while self.rollback_last():
            count += 1
        return count

    def _generate_diff(
        self, path_str: str, original: str | None, proposed: str | None
    ) -> str:
        """Build a unified diff text block comparing original and proposed content."""
        orig_lines = original.splitlines(keepends=True) if original is not None else []
        prop_lines = proposed.splitlines(keepends=True) if proposed is not None else []

        diff = difflib.unified_diff(
            orig_lines,
            prop_lines,
            fromfile=f"a/{path_str}",
            tofile=f"b/{path_str}",
        )
        return "".join(diff)
