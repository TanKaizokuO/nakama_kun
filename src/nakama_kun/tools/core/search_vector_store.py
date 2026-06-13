from __future__ import annotations

import os
from typing import Any

from nakama_kun.rag import get_retriever
from nakama_kun.tools.interfaces import BaseTool, ToolResult


class SearchVectorStoreTool(BaseTool):
    """Query the local workspace vector database for matching code chunks and documentation."""

    name = "search_vector_store"
    description = (
        "Search the local workspace vector database for matching code chunks, documentation, "
        "and historical task contexts using semantic similarity search. Returns matching text blocks "
        "with file paths, line ranges, and relevance."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language query or code search term.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results to return. Defaults to 5.",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(self, workspace_root: str | None = None) -> None:
        self._workspace_root = workspace_root or os.getcwd()

    async def execute(self, **kwargs: Any) -> ToolResult:  # noqa: ANN401
        query: str = kwargs.get("query", "")
        limit: int = kwargs.get("limit", 5)

        if not query:
            return ToolResult(success=False, error="'query' argument is required.")

        retriever = get_retriever(self._workspace_root)
        if retriever is None:
            return ToolResult(
                success=False,
                error=(
                    "Vector index does not exist or RAG is disabled. "
                    "You must build the index first using 'nakama_kun RAG build' command."
                ),
            )

        chunks = retriever.retrieve(query, limit=limit)
        if not chunks:
            return ToolResult(
                success=True,
                output=f"No matching contexts found in the vector index for: '{query}'",
            )

        output_lines = [f"Found {len(chunks)} relevant context chunk(s) in vector store:"]
        for idx, chunk in enumerate(chunks, 1):
            path = chunk.metadata.get("path", "unknown")
            chunk_type = chunk.metadata.get("type", "file")

            if chunk_type == "task":
                header = f"\n--- Match #{idx}: Historical Task `{path}` ---"
            else:
                lang = chunk.metadata.get("language", "Text")
                line_start = chunk.metadata.get("line_start", 1)
                line_end = chunk.metadata.get("line_end", 1)
                header = f"\n--- Match #{idx}: File `{path}` (Lines {line_start}-{line_end}, Language: {lang}) ---"

            symbols = chunk.metadata.get("symbols", "")
            if symbols:
                header += f"\nSymbols: {symbols}"

            output_lines.append(header)
            output_lines.append(chunk.content)

        return ToolResult(success=True, output="\n".join(output_lines))
