from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel

from nakama_kun.ai.models.message import Message
from nakama_kun.mcp.manager import MCPManager
from nakama_kun.orchestration.nodes import RESEARCH_THRESHOLD
from nakama_kun.orchestration.workflow import build_agent_graph
from nakama_kun.tools.safety import assert_within_workspace
from nakama_kun.web.auth import (
    check_auth_token,
    check_websocket_auth,
)
from nakama_kun.web.service_wiring import (
    active_connections,
    get_web_context,
    pending_approvals,
)

app = FastAPI(
    title="Nakama-kun Web Interface",
    description="Exposes Nakama-kun CLI capabilities in a premium web dashboard.",
    version="1.0.0",
)

# Allow CORS for development environments
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_headers=["*"],
    allow_methods=["*"],
)


class PromptRequest(BaseModel):
    text: str


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/status", dependencies=[Depends(check_auth_token)])
async def get_status() -> dict[str, Any]:
    """Retrieve current service configuration, tool status, and RAG/MCP metadata."""
    ctx = get_web_context()
    
    # Check MCP servers status
    mcp_manager = MCPManager(workspace_root=ctx.workspace_root)
    mcp_servers = []
    configs = mcp_manager.settings.load_servers(ctx.workspace_root)
    for name in configs:
        mcp_servers.append({
            "name": name,
            "connected": name in getattr(mcp_manager, "clients", {}),
        })
        
    return {
        "workspace_root": ctx.workspace_root,
        "model": ctx.settings.openrouter_model,
        "rag_enabled": ctx.vector_store is not None,
        "rag_db_path": getattr(ctx.vector_store, "db_path", None) if ctx.vector_store else None,
        "tools": ctx.tool_registry.names(),
        "mcp_servers": mcp_servers,
    }


@app.get("/api/workspace/files", dependencies=[Depends(check_auth_token)])
async def list_workspace_files() -> list[dict[str, Any]]:
    """Recursively list all files in the workspace (excluding common ignores)."""
    ctx = get_web_context()
    ignore_dirs = {".git", "__pycache__", ".venv", ".pytest_cache", ".nakama_rag", ".nakama_memory"}
    
    files_list = []
    root_path = Path(ctx.workspace_root)
    
    for root, dirs, files in os.walk(root_path):
        # Filter ignore dirs in-place
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for file in files:
            full_path = Path(root) / file
            try:
                rel_path = full_path.relative_to(root_path)
                files_list.append({
                    "name": file,
                    "path": str(rel_path),
                    "size": full_path.stat().st_size,
                })
            except Exception:
                continue
                
    return files_list


@app.get("/api/workspace/file", dependencies=[Depends(check_auth_token)])
async def get_file_content(path: str = Query(..., description="Relative file path")) -> dict[str, Any]:
    """Retrieve content of a file inside the workspace safely."""
    ctx = get_web_context()
    try:
        # Prevent path escape
        safe_path = assert_within_workspace(path, ctx.workspace_root)
        if not safe_path.is_file():
            raise HTTPException(status_code=400, detail="Path is not a file")
            
        content = safe_path.read_text(encoding="utf-8")
        return {"path": path, "content": content}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/memory/conversations", dependencies=[Depends(check_auth_token)])
async def get_conversations() -> list[dict[str, Any]]:
    """List recent SQLite conversations."""
    ctx = get_web_context()
    try:
        return ctx.memory_repo.get_conversations(limit=50)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch conversations: {e}") from e


@app.get("/api/memory/conversations/{id}/messages", dependencies=[Depends(check_auth_token)])
async def get_conversation_messages(id: str) -> list[dict[str, Any]]:
    """Retrieve message history for a conversation."""
    ctx = get_web_context()
    try:
        messages = ctx.memory_repo.get_messages(id)
        return [{"role": msg.role, "content": msg.content} for msg in messages]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch messages: {e}") from e


@app.delete("/api/memory/conversations/{id}", dependencies=[Depends(check_auth_token)])
async def delete_conversation(id: str) -> dict[str, str]:
    """Delete a conversation."""
    ctx = get_web_context()
    try:
        ctx.memory_repo.clear_conversation(id)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/memory/tasks", dependencies=[Depends(check_auth_token)])
async def get_tasks() -> list[dict[str, Any]]:
    """List recent tasks."""
    ctx = get_web_context()
    try:
        return ctx.memory_repo.list_tasks(limit=50)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch tasks: {e}") from e


@app.post("/api/rag/build", dependencies=[Depends(check_auth_token)])
async def build_rag_index() -> dict[str, str]:
    """Trigger clean RAG build."""
    ctx = get_web_context()
    if ctx.indexer is None:
        raise HTTPException(status_code=400, detail="RAG system is disabled.")
    try:
        ctx.indexer.build()
        return {"status": "ok", "message": "RAG index successfully built."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/rag/refresh", dependencies=[Depends(check_auth_token)])
async def refresh_rag_index() -> dict[str, str]:
    """Incrementally synchronize RAG index."""
    ctx = get_web_context()
    if ctx.indexer is None:
        raise HTTPException(status_code=400, detail="RAG system is disabled.")
    try:
        ctx.indexer.refresh()
        return {"status": "ok", "message": "RAG index successfully refreshed."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/rag/clear", dependencies=[Depends(check_auth_token)])
async def clear_rag_index() -> dict[str, str]:
    """Clear vector index."""
    ctx = get_web_context()
    if ctx.vector_store is None:
        raise HTTPException(status_code=400, detail="RAG vector store is disabled.")
    try:
        ctx.vector_store.clear()
        return {"status": "ok", "message": "RAG vector database cleared."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/approvals/pending", dependencies=[Depends(check_auth_token)])
async def list_pending_approvals() -> list[dict[str, Any]]:
    """Retrieve details on currently blocking approvals."""
    return [
        {
            "id": pid,
            "file_path": str(proposal.file_path),
            "change_type": proposal.change_type,
            "diff": proposal.diff_text,
        }
        for pid, (proposal, _, _) in pending_approvals.items()
    ]


@app.post("/api/approvals/{proposal_id}/approve", dependencies=[Depends(check_auth_token)])
async def approve_proposal(proposal_id: str) -> dict[str, str]:
    """Approve a blocking file change proposal."""
    if proposal_id not in pending_approvals:
        raise HTTPException(status_code=404, detail="Proposal not found")
        
    _, event, result = pending_approvals[proposal_id]
    result["approved"] = True
    event.set()
    return {"status": "ok"}


@app.post("/api/approvals/{proposal_id}/reject", dependencies=[Depends(check_auth_token)])
async def reject_proposal(proposal_id: str) -> dict[str, str]:
    """Reject a blocking file change proposal."""
    if proposal_id not in pending_approvals:
        raise HTTPException(status_code=404, detail="Proposal not found")
        
    _, event, result = pending_approvals[proposal_id]
    result["approved"] = False
    event.set()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# WebSocket agent loop handler
# ---------------------------------------------------------------------------

@app.websocket("/api/ws/agent")
async def websocket_agent_endpoint(websocket: WebSocket) -> None:
    """Stateful WebSocket connection for streaming Ask, Plan, and Agent modes."""
    await websocket.accept()
    if not await check_websocket_auth(websocket):
        return

    active_connections.add(websocket)
    ctx = get_web_context()

    try:
        while True:
            data = await websocket.receive_json()
            req_type = data.get("type")
            text = data.get("text", "").strip()

            if not text:
                continue

            if req_type == "ask":
                await run_web_ask_flow(websocket, ctx, text)
            elif req_type == "plan":
                await run_web_plan_flow(websocket, ctx, text)
            elif req_type == "agent":
                # Spawn agent loop
                await run_web_agent_flow(websocket, ctx, text)
            else:
                await websocket.send_json({"type": "error", "message": f"Unknown action: {req_type}"})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        active_connections.discard(websocket)


# ---------------------------------------------------------------------------
# Flow Orchestrators
# ---------------------------------------------------------------------------

async def run_web_ask_flow(websocket: WebSocket, ctx: Any, text: str) -> None:
    """Run Ask Mode token-by-token stream over websocket."""
    from nakama_kun.ai.prompts.system_prompt import ASK_SYSTEM_PROMPT
    from nakama_kun.rag import get_retriever
    from nakama_kun.workspace.context import WorkspaceContextBuilder

    try:
        # Load memory session or create new one
        conv_id = None
        try:
            latest = ctx.memory_repo.get_latest_conversation("ask")
            if latest:
                conv_id = latest["id"]
                ctx.chat_service.history = ctx.memory_repo.get_messages(conv_id)
            else:
                conv_id = ctx.memory_repo.create_conversation("Web Ask Session", "ask")
        except Exception:
            pass

        # Build workspace & RAG context
        try:
            workspace_context = WorkspaceContextBuilder().build_summary()
            system_prompt = f"{ASK_SYSTEM_PROMPT}\n\n{workspace_context}"
            retriever = get_retriever(ctx.workspace_root)
            if retriever is not None:
                rag_context = retriever.retrieve_formatted_context(text)
                if rag_context:
                    system_prompt += f"\n\n{rag_context}"
            ctx.chat_service.system_prompt = system_prompt
        except Exception:
            ctx.chat_service.system_prompt = ASK_SYSTEM_PROMPT

        response_content = ""
        async for token in ctx.chat_service.chat_stream(text):
            response_content += token
            await websocket.send_json({"type": "token", "content": token})

        # Save to database
        if conv_id:
            try:
                if len(ctx.chat_service.history) >= 2:
                    ctx.memory_repo.add_message(conv_id, ctx.chat_service.history[-2])
                    ctx.memory_repo.add_message(conv_id, ctx.chat_service.history[-1])
            except Exception:
                pass

        await websocket.send_json({"type": "done", "final_response": response_content})

    except Exception as e:
        await websocket.send_json({"type": "error", "message": f"Ask flow error: {e}"})


async def run_web_plan_flow(websocket: WebSocket, ctx: Any, text: str) -> None:
    """Run Plan Mode and return structured details."""
    try:
        conv_id = None
        try:
            latest = ctx.memory_repo.get_latest_conversation("plan")
            if latest:
                conv_id = latest["id"]
                ctx.planner_service.history = ctx.memory_repo.get_messages(conv_id)
            else:
                conv_id = ctx.memory_repo.create_conversation("Web Plan Session", "plan")
        except Exception:
            pass

        await websocket.send_json({"type": "agent_node", "node": "planning", "status": "running"})
        plan, raw_text = await ctx.planner_service.plan(text)
        
        # Save to database
        if conv_id:
            try:
                if len(ctx.planner_service.history) >= 2:
                    ctx.memory_repo.add_message(conv_id, ctx.planner_service.history[-2])
                    ctx.memory_repo.add_message(conv_id, ctx.planner_service.history[-1])
            except Exception:
                pass

        payload = {
            "type": "plan",
            "raw_text": raw_text,
            "goal_summary": plan.goal_summary if plan else None,
            "targets": plan.targets if plan else [],
            "assumptions": plan.assumptions if plan else [],
            "ordered_steps": plan.ordered_steps if plan else [],
            "risks": plan.risks if plan else [],
            "validation_checklist": plan.validation_checklist if plan else [],
        }
        await websocket.send_json(payload)
        await websocket.send_json({"type": "agent_node", "node": "planning", "status": "completed"})

    except Exception as e:
        await websocket.send_json({"type": "error", "message": f"Planning flow error: {e}"})


async def run_web_agent_flow(websocket: WebSocket, ctx: Any, text: str) -> None:
    """Execute LangGraph orchestration workflows, sending step logs and node state changes to websocket."""
    import uuid

    from nakama_kun.mcp.manager import MCPManager
    from nakama_kun.rag import get_retriever

    task_id = str(uuid.uuid4())
    with contextlib.suppress(Exception):
        ctx.memory_repo.save_task_metadata(task_id, text, "running")

    mcp_manager = MCPManager(workspace_root=ctx.workspace_root, approval_provider=ctx.approval_provider)
    
    try:
        # Load MCP tools
        await mcp_manager.connect_all()
        mcp_tools = await mcp_manager.get_tools()
        for t in mcp_tools:
            ctx.tool_registry.register(t)

        # Build graph
        graph = build_agent_graph(
            chat_service=ctx.chat_service,
            planner_service=ctx.planner_service,
            tool_registry=ctx.tool_registry,
            tool_router=ctx.tool_router,
        ).compile()

        initial_messages = []
        retriever = get_retriever(ctx.workspace_root)
        if retriever is not None:
            rag_context = retriever.retrieve_formatted_context(text)
            if rag_context:
                initial_messages.append(Message(role="system", content=rag_context))

        initial_state = {
            "goal": text,
            "plan": None,
            "required_artifacts": [],
            "created_artifacts": [],
            "missing_artifacts": [],
            "research_budget_remaining": RESEARCH_THRESHOLD,
            "delivery_mode": False,
            "retry_memory": {
                "completed_actions": [],
                "failed_actions": [],
                "failed_validations": [],
                "reviewer_feedback": [],
                "failed_attempt_signatures": [],
            },
            "messages": initial_messages,
            "tool_results": [],
            "reviewer_feedback": None,
            "retry_count": 0,
            "final_response": None,
            "status": "planning",
            "active_agent": "",
            "agent_outputs": {},
            "agent_metrics": {},
        }

        # Keep socket posted on each step of the LangGraph execution
        last_node = None
        async for update in graph.astream(initial_state, stream_mode="updates"):
            # Format update: e.g. {"node_name": state_changes}
            node_name = list(update.keys())[0]
            node_data = list(update.values())[0]
            
            if last_node and last_node != node_name:
                await websocket.send_json({"type": "agent_node", "node": last_node, "status": "completed"})
                
            last_node = node_name
            await websocket.send_json({"type": "agent_node", "node": node_name, "status": "running"})
            
            # Send latest logs or tool call results
            if "tool_results" in node_data and node_data["tool_results"]:
                latest_tool = node_data["tool_results"][-1]
                await websocket.send_json({
                    "type": "agent_log",
                    "log": f"🔧 Executed tool: {latest_tool.get('tool')} | Success: {latest_tool.get('success')}"
                })

        # Completed graph loop
        if last_node:
            await websocket.send_json({"type": "agent_node", "node": last_node, "status": "completed"})

        # Retrieve final response from memory/state
        # Since state values accumulate, we read from memory repo
        final_state = await graph.ainvoke(initial_state)
        final_answer = final_state.get("final_response") or "Task completed."
        
        with contextlib.suppress(Exception):
            ctx.memory_repo.save_task_metadata(task_id, text, "done")

        await websocket.send_json({"type": "done", "final_response": final_answer})

    except Exception as e:
        with contextlib.suppress(Exception):
            ctx.memory_repo.save_task_metadata(task_id, text, "failed")
        await websocket.send_json({"type": "error", "message": f"Agent loop error: {e}"})
    finally:
        await mcp_manager.disconnect_all()


# ---------------------------------------------------------------------------
# Static assets mount (Serves frontend web app)
# ---------------------------------------------------------------------------

static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/", StaticFiles(directory=str(static_path), html=True), name="static")
