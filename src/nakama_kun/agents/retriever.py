from __future__ import annotations

import os
from typing import Any
from loguru import logger

from nakama_kun.agents.base import BaseAgent
from nakama_kun.agents.models import RetrievalPackage, parse_retrieval_package
from nakama_kun.ai.models.message import Message
from nakama_kun.rag.retriever import RepositoryKnowledgeService, get_retriever


class RetrieverAgent(BaseAgent):
    """Retriever Agent searches the repository, performs RAG retrieval, gathers context, and performs dependency analysis."""

    def __init__(self, chat_service: Any, workspace_root: str | None = None) -> None:
        from nakama_kun.agents.prompts import RETRIEVER_AGENT_PROMPT
        super().__init__(
            name="RetrieverAgent",
            role="retriever",
            system_prompt=RETRIEVER_AGENT_PROMPT,
            chat_service=chat_service,
        )
        self.workspace_root = workspace_root

    @property
    def retrieval_history(self) -> list[Any]:
        """Returns the history of retrievals performed by the retriever."""
        return self.memory.get("retrieval_history", [])

    async def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        logger.info("[RetrieverAgent] Starting repository retrieval and dependency analysis...")
        goal = state["goal"]

        # 1. Query RAG and search codebase
        retriever_obj = get_retriever(self.workspace_root)
        results = []
        if retriever_obj is not None:
            try:
                results = retriever_obj.retrieve(goal, limit=10)
            except Exception as e:
                logger.warning(f"[RetrieverAgent] RAG retrieval failed: {e}")

        # 2. Dependency Analysis
        related_files = []
        try:
            knowledge_svc = RepositoryKnowledgeService(retriever=retriever_obj, workspace_root=self.workspace_root)
            for r in results:
                rel = knowledge_svc.find_related_files(r.source_path)
                related_files.extend(rel)
            related_files = sorted(list(set(related_files)))
        except Exception as e:
            logger.warning(f"[RetrieverAgent] Dependency analysis failed: {e}")

        # 3. Format context string
        candidates_str = ""
        for i, r in enumerate(results):
            candidates_str += f"Candidate {i+1}:\n"
            candidates_str += f"  Path: {r.source_path}\n"
            candidates_str += f"  Type: {r.source_type}\n"
            candidates_str += f"  Score: {r.score}\n"
            candidates_str += f"  Snippet:\n{r.content}\n"
            candidates_str += "-" * 40 + "\n"

        if related_files:
            candidates_str += "\nDependency / Related Files:\n"
            for f in related_files:
                candidates_str += f"  - {f}\n"

        # 4. Formulate prompt for LLM structuring
        workspace_context = state.get("workspace_context") or ""
        user_prompt = (
            f"Goal: {goal}\n"
            f"Workspace Context: {workspace_context}\n\n"
            f"### Candidate Retrieval Chunks:\n{candidates_str}\n"
            "Please analyze the candidates and dependencies, select the most relevant files/documentation, "
            "and produce a structured RetrievalPackage JSON with 'retrieved_files', 'summaries', 'citations', and 'relevance_scores'."
        )

        messages = [
            Message(role="system", content=self.system_prompt),
            Message(role="user", content=user_prompt),
        ]

        try:
            response = await self.chat_service.provider.generate(messages)
            raw_text = response.content or ""
            pkg = parse_retrieval_package(raw_text)
        except Exception as e:
            logger.warning(f"[RetrieverAgent] LLM structuring generation failed: {e}")
            pkg = None

        if not pkg:
            logger.warning("[RetrieverAgent] Failed to parse RetrievalPackage. Falling back to deterministic RAG mapping.")
            retrieved_paths = [r.source_path for r in results]
            pkg = RetrievalPackage(
                retrieved_files=retrieved_paths,
                summaries={r.source_path: r.content[:300] for r in results},
                citations={r.source_path: f"Source: {r.source_path}" for r in results},
                relevance_scores={r.source_path: r.score for r in results},
            )

        relevant_files = pkg.retrieved_files
        documentation = "\n\n".join(
            f"Documentation/Summary for {f}:\n{pkg.summaries.get(f, '')}"
            for f in relevant_files
        )

        # 5. Build history and handoff outputs
        history_entry = {
            "agent": self.name,
            "thought": f"Gathered {len(relevant_files)} relevant files for goal.",
            "handoff": pkg.model_dump(),
        }

        # Conforming to contract: return structured outputs only
        return {
            "retrieval_package": pkg,
            "relevant_files": relevant_files,
            "documentation": documentation,
            "agent_history": [history_entry],
            "messages": [
                Message(role="assistant", content=f"Retrieved relevant codebase context for task. Relevant files: {', '.join(relevant_files)}")
            ],
            "status": "executing",
        }
