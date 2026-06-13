from __future__ import annotations

from loguru import logger

from nakama_kun.rag.vector_store import DocumentChunk, VectorStore


class Retriever:
    """Retrieves relevant document chunks and formats them into context for LLM prompts."""

    def __init__(self, vector_store: VectorStore) -> None:
        self.vector_store = vector_store

    def retrieve(self, query: str, limit: int = 5) -> list[DocumentChunk]:
        """Perform search query on vector store and catch exceptions gracefully."""
        try:
            return self.vector_store.search(query, limit=limit)
        except Exception as exc:
            logger.warning(f"RAG retrieval query failed: {exc}")
            return []

    def retrieve_formatted_context(self, query: str, limit: int = 5) -> str:
        """Query vector database and format the matching documents as Markdown segment."""
        chunks = self.retrieve(query, limit=limit)
        if not chunks:
            return ""

        context_blocks = []
        context_blocks.append("## Retrieved Workspace Context")
        context_blocks.append(
            "Use the following retrieved project context and history to ground your answers. "
            "IMPORTANT: When referring to or copying from a retrieved file, "
            "you MUST cite the file path and line numbers using square brackets (e.g. `[path/to/file:10-20]`)."
        )

        for idx, chunk in enumerate(chunks, 1):
            path = chunk.metadata.get("path", "unknown")
            chunk_type = chunk.metadata.get("type", "file")

            if chunk_type == "task":
                header = f"### [Context #{idx}] Historical Task Reference: `{path}`"
            else:
                lang = chunk.metadata.get("language", "Text")
                line_start = chunk.metadata.get("line_start", 1)
                line_end = chunk.metadata.get("line_end", 1)
                header = f"### [Context #{idx}] File: `{path}` (lines {line_start}-{line_end}, language: {lang})"

            symbols = chunk.metadata.get("symbols", "")
            symbols_line = f"Symbols in chunk: {symbols}\n" if symbols else ""

            # Embed content within codeblock if it's a file
            if chunk_type == "task":
                formatted_body = f"```\n{chunk.content}\n```"
            else:
                lang_code = lang.lower() if lang != "C/C++ Header" else "cpp"
                # Map markdown, python, etc.
                if "python" in lang_code:
                    lang_code = "python"
                elif "typescript" in lang_code:
                    lang_code = "typescript"
                elif "javascript" in lang_code:
                    lang_code = "javascript"
                elif "markdown" in lang_code:
                    lang_code = "markdown"
                else:
                    lang_code = ""

                formatted_body = f"```{lang_code}\n{chunk.content}\n```"

            context_blocks.append(f"{header}\n{symbols_line}{formatted_body}")

        return "\n\n".join(context_blocks) + "\n"
