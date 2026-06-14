from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

from fastapi import WebSocket
from loguru import logger

from nakama_kun.ai.config import AISettings
from nakama_kun.ai.providers.openrouter_provider import OpenRouterProvider
from nakama_kun.ai.services.chat_service import ChatService
from nakama_kun.ai.services.planner_service import PlannerService
from nakama_kun.memory import get_memory_repository
from nakama_kun.rag import get_indexer, get_vector_store
from nakama_kun.safety.manager import SafetyManager
from nakama_kun.safety.models import ApprovalProvider, FileChangeProposal
from nakama_kun.tools import ToolRouter, build_default_registry

# Registry of active WebSockets to broadcast messages (e.g. pending approvals, logs)
active_connections: set[WebSocket] = set()

# Pending approvals registry: approval_id -> (proposal, event, result_dict)
pending_approvals: dict[str, tuple[FileChangeProposal, asyncio.Event, dict[str, Any]]] = {}


class WebApprovalProvider(ApprovalProvider):
    """Approval provider for the Web UI.

    Queues proposals and alerts clients via WebSockets, pausing tool execution until
    the user approves or rejects via the API.
    """

    async def request_approval(self, proposal: FileChangeProposal) -> bool:
        proposal_id = str(uuid.uuid4())
        event = asyncio.Event()
        result = {"approved": False}

        # Store proposal
        pending_approvals[proposal_id] = (proposal, event, result)

        # Notify all active WebSockets about the pending approval
        logger.info(f"WebApprovalProvider: proposed change {proposal_id} on {proposal.file_path}")
        await broadcast_message({
            "type": "approval_required",
            "id": proposal_id,
            "file_path": str(proposal.file_path),
            "change_type": proposal.change_type,
            "diff": proposal.diff_text,
        })

        # Wait for the user response via /api/approvals/{id}/approve or reject
        await event.wait()

        # Clean up and return
        pending_approvals.pop(proposal_id, None)
        return result["approved"]


async def broadcast_message(message: dict[str, Any]) -> None:
    """Send a JSON payload to all active WebSocket clients."""
    if not active_connections:
        return
    
    dead_connections = set()
    for websocket in active_connections:
        try:
            await websocket.send_json(message)
        except Exception:
            dead_connections.add(websocket)
            
    active_connections.difference_update(dead_connections)


class WebServiceContext:
    """Registry container for wired services."""

    def __init__(self, workspace_root: str | None = None) -> None:
        self.workspace_root = workspace_root or os.getcwd()
        
        # Preload RAG models on web application startup
        try:
            from nakama_kun.rag.model_manager import preload_rag_models
            preload_rag_models()
        except Exception as e:
            logger.error(f"Failed to preload RAG models: {e}")
        
        # 1. AI Stack
        self.settings = AISettings()
        self.provider = OpenRouterProvider(self.settings)
        self.chat_service = ChatService(self.provider)
        self.planner_service = PlannerService(self.chat_service)
        
        # 2. Safety Stack
        self.safety_manager = SafetyManager(self.workspace_root)
        self.approval_provider = WebApprovalProvider()
        
        # 3. Tool registry with web approval provider injected
        self.tool_registry = build_default_registry(
            workspace_root=self.workspace_root,
            safety_manager=self.safety_manager,
            approval_provider=self.approval_provider,
        )
        self.tool_router = ToolRouter(self.tool_registry)
        
        # 4. Memory Repository
        self.memory_repo = get_memory_repository()
        
        # 5. RAG indexing
        self.vector_store = get_vector_store(self.workspace_root)
        self.indexer = get_indexer(self.workspace_root)


# Global single instance initialized on web startup
_web_context: WebServiceContext | None = None


def get_web_context(workspace_root: str | None = None) -> WebServiceContext:
    """Get or initialize the global WebServiceContext."""
    global _web_context
    if _web_context is None:
        _web_context = WebServiceContext(workspace_root)
    return _web_context
