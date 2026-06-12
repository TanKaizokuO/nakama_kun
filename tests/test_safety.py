from __future__ import annotations

from pathlib import Path

import pytest

from nakama_kun.safety.manager import SafetyManager
from nakama_kun.safety.models import AutoApprovalProvider
from nakama_kun.tools.core.write_file import WriteFileTool
from nakama_kun.tools.exceptions import PathEscapeError


def test_safety_manager_diff_creation(tmp_path: Path) -> None:
    manager = SafetyManager(workspace_root=tmp_path)
    file_path = tmp_path / "new_file.txt"

    # Create proposal for a new file
    proposal = manager.propose_change(file_path, "proposed content")

    assert proposal.change_type == "create"
    assert proposal.original_content is None
    assert proposal.proposed_content == "proposed content"
    assert "proposed content" in proposal.diff_text


def test_safety_manager_diff_update(tmp_path: Path) -> None:
    manager = SafetyManager(workspace_root=tmp_path)
    file_path = tmp_path / "existing.txt"
    file_path.write_text("original text", encoding="utf-8")

    # Update proposal
    proposal = manager.propose_change(file_path, "updated text")

    assert proposal.change_type == "update"
    assert proposal.original_content == "original text"
    assert proposal.proposed_content == "updated text"
    assert "-original text" in proposal.diff_text
    assert "+updated text" in proposal.diff_text


@pytest.mark.anyio
async def test_safety_manager_apply_and_reject(tmp_path: Path) -> None:
    manager = SafetyManager(workspace_root=tmp_path)
    file_path = tmp_path / "target.txt"

    # Proposal
    proposal = manager.propose_change(file_path, "some content")

    # 1. Reject
    applied = await manager.apply_proposal(proposal, AutoApprovalProvider(approve=False))
    assert not applied
    assert not file_path.exists()
    assert len(manager.history) == 0

    # 2. Approve
    applied = await manager.apply_proposal(proposal, AutoApprovalProvider(approve=True))
    assert applied
    assert file_path.exists()
    assert file_path.read_text(encoding="utf-8") == "some content"
    assert len(manager.history) == 1


@pytest.mark.anyio
async def test_safety_manager_rollback_creation(tmp_path: Path) -> None:
    manager = SafetyManager(workspace_root=tmp_path)
    file_path = tmp_path / "created.txt"

    proposal = manager.propose_change(file_path, "new file content")
    
    # Apply change
    await manager.apply_proposal(proposal, AutoApprovalProvider(approve=True))
    assert file_path.exists()

    # Rollback should delete it
    success = manager.rollback_last()
    assert success
    assert not file_path.exists()
    assert len(manager.history) == 0


@pytest.mark.anyio
async def test_safety_manager_rollback_update(tmp_path: Path) -> None:
    manager = SafetyManager(workspace_root=tmp_path)
    file_path = tmp_path / "file.txt"
    file_path.write_text("v1 content", encoding="utf-8")

    proposal = manager.propose_change(file_path, "v2 content")
    await manager.apply_proposal(proposal, AutoApprovalProvider(approve=True))
    assert file_path.read_text(encoding="utf-8") == "v2 content"

    # Rollback should restore v1 content
    success = manager.rollback_last()
    assert success
    assert file_path.read_text(encoding="utf-8") == "v1 content"


def test_safety_manager_path_escape(tmp_path: Path) -> None:
    manager = SafetyManager(workspace_root=tmp_path)
    outside_path = tmp_path.parent / "escape.txt"

    # Try to propose change outside workspace
    with pytest.raises(PathEscapeError):
        manager.propose_change(outside_path, "content")


@pytest.mark.anyio
async def test_write_file_tool_safety_integration(tmp_path: Path) -> None:
    # Set up WriteFileTool with AutoApprovalProvider and SafetyManager
    manager = SafetyManager(workspace_root=tmp_path)
    reject_provider = AutoApprovalProvider(approve=False)
    approve_provider = AutoApprovalProvider(approve=True)

    file_path = tmp_path / "tool_test.txt"

    # Tool with reject provider
    tool_reject = WriteFileTool(
        workspace_root=str(tmp_path),
        safety_manager=manager,
        approval_provider=reject_provider,
    )
    result = await tool_reject.execute(path=str(file_path), content="content")
    assert not result.success
    assert "rejected" in result.error.lower()
    assert not file_path.exists()

    # Tool with approve provider
    tool_approve = WriteFileTool(
        workspace_root=str(tmp_path),
        safety_manager=manager,
        approval_provider=approve_provider,
    )
    result = await tool_approve.execute(path=str(file_path), content="content")
    assert result.success
    assert file_path.exists()
    assert file_path.read_text(encoding="utf-8") == "content"
