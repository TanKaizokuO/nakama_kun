from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from nakama_kun.web.app import app
from nakama_kun.web.auth import get_session_token
from nakama_kun.web.service_wiring import get_web_context, pending_approvals
from nakama_kun.safety.models import FileChangeProposal


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def valid_token() -> str:
    return get_session_token()


def test_auth_required_endpoints(client: TestClient) -> None:
    """Ensure accessing sensitive API endpoints without or with invalid tokens returns 401."""
    # 1. No token
    res = client.get("/api/status")
    assert res.status_code == 401

    # 2. Invalid token
    res = client.get("/api/status", headers={"X-Web-Token": "wrong-token"})
    assert res.status_code == 401


def test_status_endpoint_success(client: TestClient, valid_token: str) -> None:
    """Ensure status API endpoint successfully returns config data with a valid token."""
    res = client.get("/api/status", headers={"X-Web-Token": valid_token})
    assert res.status_code == 200
    data = res.json()
    assert "workspace_root" in data
    assert "model" in data
    assert "rag_enabled" in data


def test_workspace_files_api(client: TestClient, valid_token: str) -> None:
    """Ensure workspace files can be listed with valid token."""
    res = client.get("/api/workspace/files", headers={"X-Web-Token": valid_token})
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)


def test_workspace_file_escape_protection(client: TestClient, valid_token: str) -> None:
    """Ensure directory traversal/path escape outside of the workspace is blocked."""
    # Path escaping query
    res = client.get(
        "/api/workspace/file",
        params={"path": "../../escape.txt"},
        headers={"X-Web-Token": valid_token},
    )
    assert res.status_code == 400


@pytest.mark.anyio
async def test_web_approval_provider_flow(client: TestClient, valid_token: str) -> None:
    """Ensure WebApprovalProvider blocks execution and resumes on user approve/reject API calls."""
    ctx = get_web_context()
    proposal = FileChangeProposal(
        file_path=Path(ctx.workspace_root) / "test_dummy.txt",
        change_type="create",
        original_content=None,
        proposed_content="Hello world",
        diff_text="+++ b/test_dummy.txt\n+Hello world",
    )

    # We mock broadcast_message to prevent Websocket broadcast side-effects
    with patch("nakama_kun.web.service_wiring.broadcast_message", new_callable=AsyncMock) as mock_broadcast:
        # We start the request_approval in a background thread or task so we can approve it via the REST API
        approval_task = asyncio.create_task(ctx.approval_provider.request_approval(proposal))

        # Give it a millisecond to yield control and queue itself
        await asyncio.sleep(0.1)

        # Check that it's registered in pending_approvals
        assert len(pending_approvals) == 1
        proposal_id = list(pending_approvals.keys())[0]

        # Call the approval API
        res = client.post(
            f"/api/approvals/{proposal_id}/approve",
            headers={"X-Web-Token": valid_token},
        )
        assert res.status_code == 200

        # Wait for the task to finish and check the decision
        approved = await approval_task
        assert approved is True
        assert len(pending_approvals) == 0
        mock_broadcast.assert_called_once()


@pytest.mark.anyio
async def test_web_approval_provider_reject(client: TestClient, valid_token: str) -> None:
    """Ensure WebApprovalProvider blocks execution and resumes as False on reject API calls."""
    ctx = get_web_context()
    proposal = FileChangeProposal(
        file_path=Path(ctx.workspace_root) / "test_dummy.txt",
        change_type="delete",
        original_content="Some content",
        proposed_content=None,
        diff_text="--- a/test_dummy.txt",
    )

    with patch("nakama_kun.web.service_wiring.broadcast_message", new_callable=AsyncMock):
        approval_task = asyncio.create_task(ctx.approval_provider.request_approval(proposal))
        await asyncio.sleep(0.1)

        proposal_id = list(pending_approvals.keys())[0]

        # Call the reject API
        res = client.post(
            f"/api/approvals/{proposal_id}/reject",
            headers={"X-Web-Token": valid_token},
        )
        assert res.status_code == 200

        approved = await approval_task
        assert approved is False
        assert len(pending_approvals) == 0
