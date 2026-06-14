from __future__ import annotations

import time
import math
import os
import re
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from loguru import logger

from nakama_kun.rag.vector_store import DocumentChunk, VectorStore, ChromaVectorStore


@dataclass
class RetrievalResult:
    """Represents a single search match with content, location, type, and score."""
    content: str
    source_path: str
    source_type: str
    score: float
    metadata: dict[str, Any]


@dataclass
class RetrievalAnalytics:
    """Represents stats captured during a single retrieval event."""
    query: str
    latency_ms: float
    total_raw_results: int
    total_final_results: int
    results: list[dict[str, Any]] = field(default_factory=list)


class BGEReranker:
    """Reranks candidate chunks based on a query using BGE-Reranker cross-encoder or falls back to a lexical overlap scorer."""

    def __init__(self, use_fallback: bool = False) -> None:
        self._model = None
        self._use_fallback = use_fallback

        if not self._use_fallback:
            try:
                from sentence_transformers import CrossEncoder
                self._model = CrossEncoder("BAAI/bge-reranker-base")
            except Exception:
                logger.warning("sentence-transformers not installed or BGE-Reranker failed to load. Falling back to deterministic lexical reranking.")
                self._use_fallback = True

    def rerank(self, query: str, chunks: list[DocumentChunk]) -> list[tuple[DocumentChunk, float]]:
        """Reranks chunks. Returns list of tuples of (DocumentChunk, score)."""
        if not chunks:
            return []

        if self._use_fallback or self._model is None:
            return self._fallback_rerank(query, chunks)

        try:
            pairs = [(query, chunk.content) for chunk in chunks]
            scores = self._model.predict(pairs)
            
            results = []
            for chunk, score in zip(chunks, scores):
                try:
                    norm_score = 1.0 / (1.0 + math.exp(-float(score)))
                except OverflowError:
                    norm_score = 1.0 if score > 0 else 0.0
                results.append((chunk, norm_score))
            return results
        except Exception as e:
            logger.warning(f"BGE-Reranker execution failed: {e}. Falling back to lexical reranking.")
            return self._fallback_rerank(query, chunks)

    def _fallback_rerank(self, query: str, chunks: list[DocumentChunk]) -> list[tuple[DocumentChunk, float]]:
        """Calculates a lexical overlap similarity score for fallback reranking."""
        query_words = set(re.findall(r"\w+", query.lower()))
        results = []
        
        for idx, chunk in enumerate(chunks):
            content_words = re.findall(r"\w+", chunk.content.lower())
            
            tf = 0
            for qw in query_words:
                tf += content_words.count(qw)
                
            original_rank_score = 1.0 / (idx + 1)
            overlap_score = len(query_words.intersection(set(content_words))) / max(len(query_words), 1)
            
            final_score = 0.5 * overlap_score + 0.3 * (min(tf, 10) / 10.0) + 0.2 * original_rank_score
            results.append((chunk, final_score))
            
        return results


class ContextAssembler:
    """Deduplicates, merges adjacent line chunks, enforces token budgets, and formats retrieved workspace information."""

    def __init__(self, token_budget: int = 4000, workspace_root: str | None = None) -> None:
        self.token_budget = token_budget
        self.workspace_root = Path(workspace_root or os.getcwd()).resolve()

    def assemble(self, results: list[RetrievalResult]) -> str:
        """Assembles, deduplicates, merges, and formats retrieval results into a compact context string."""
        if not results:
            return ""

        # 1. Deduplicate by content
        seen_contents = set()
        deduped = []
        for r in results:
            content_norm = " ".join(r.content.split())
            if content_norm in seen_contents:
                continue
            seen_contents.add(content_norm)
            deduped.append(r)

        # 2. Merge overlapping or contiguous chunks from the same physical file
        file_chunks: dict[str, list[RetrievalResult]] = {}
        non_file_chunks: list[RetrievalResult] = []

        for r in deduped:
            if r.metadata.get("line_start") is not None and not r.source_path.startswith("memory://"):
                file_chunks.setdefault(r.source_path, []).append(r)
            else:
                non_file_chunks.append(r)

        merged_blocks: list[dict[str, Any]] = []

        for path, chunks in file_chunks.items():
            chunks.sort(key=lambda x: x.metadata.get("line_start", 0))
            
            merged_for_file = []
            current_block = None

            for chunk in chunks:
                start = chunk.metadata["line_start"]
                end = chunk.metadata["line_end"]
                
                if current_block is None:
                    current_block = {
                        "path": path,
                        "line_start": start,
                        "line_end": end,
                        "source_type": chunk.source_type,
                        "language": chunk.metadata.get("language", "Text"),
                        "symbols": chunk.metadata.get("symbol_names", chunk.metadata.get("symbols", "")),
                        "section_title": chunk.metadata.get("section_title", ""),
                        "chunk_contents": [chunk.content],
                    }
                else:
                    if start <= current_block["line_end"] + 1:
                        current_block["line_end"] = max(current_block["line_end"], end)
                        current_block["chunk_contents"].append(chunk.content)
                        new_symbols = chunk.metadata.get("symbol_names", chunk.metadata.get("symbols", ""))
                        if new_symbols:
                            current_symbols = current_block["symbols"]
                            if current_symbols:
                                merged_syms = set(s.strip() for s in current_symbols.split(",") if s.strip())
                                merged_syms.update(s.strip() for s in new_symbols.split(",") if s.strip())
                                current_block["symbols"] = ", ".join(sorted(merged_syms))
                            else:
                                current_block["symbols"] = new_symbols
                    else:
                        merged_for_file.append(current_block)
                        current_block = {
                            "path": path,
                            "line_start": start,
                            "line_end": end,
                            "source_type": chunk.source_type,
                            "language": chunk.metadata.get("language", "Text"),
                            "symbols": chunk.metadata.get("symbol_names", chunk.metadata.get("symbols", "")),
                            "section_title": chunk.metadata.get("section_title", ""),
                            "chunk_contents": [chunk.content],
                        }
            if current_block:
                merged_for_file.append(current_block)

            for block in merged_for_file:
                abs_path = self.workspace_root / block["path"]
                reconstructed = False
                if abs_path.exists() and abs_path.is_file():
                    try:
                        lines = abs_path.read_text(encoding="utf-8").splitlines()
                        start_idx = max(0, block["line_start"] - 1)
                        end_idx = min(len(lines), block["line_end"])
                        block_content = "\n".join(lines[start_idx:end_idx])
                        block["content"] = block_content
                        reconstructed = True
                    except Exception:
                        pass
                
                if not reconstructed:
                    block["content"] = "\n...\n".join(block["chunk_contents"])
                    
                merged_blocks.append(block)

        # Process virtual chunks
        for r in non_file_chunks:
            symbols = r.metadata.get("symbol_names", r.metadata.get("symbols", ""))
            merged_blocks.append({
                "path": r.source_path,
                "content": r.content,
                "source_type": r.source_type,
                "line_start": None,
                "line_end": None,
                "language": "Text",
                "symbols": symbols,
                "section_title": r.metadata.get("section_title", ""),
            })

        # Token budget limit
        context_blocks = []
        context_blocks.append("## Retrieved Workspace Context")
        context_blocks.append(
            "Use the following retrieved project context and history to ground your answers. "
            "IMPORTANT: When referring to or copying from a retrieved file, "
            "you MUST cite the file path and line numbers using square brackets (e.g. `[path/to/file:10-20]`)."
        )

        current_token_count = sum(len(b) // 4 for b in context_blocks)
        block_idx = 1

        for block in merged_blocks:
            path = block["path"]
            source_type = block["source_type"]
            symbols = block["symbols"]
            section_title = block["section_title"]
            content = block["content"]
            
            if path.startswith("memory://"):
                header = f"### [Context #{block_idx}] Virtual Memory Reference: `{path}`"
            else:
                line_start = block["line_start"]
                line_end = block["line_end"]
                lang = block["language"]
                header = f"### [Context #{block_idx}] File: `{path}` (lines {line_start}-{line_end}, language: {lang})"
                
            symbols_line = f"Symbols: {symbols}\n" if symbols else ""
            section_line = f"Section: {section_title}\n" if section_title else ""
            
            lang_code = block.get("language", "text").lower()
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

            formatted_body = f"```{lang_code}\n{content}\n```"
            block_text = f"{header}\n{symbols_line}{section_line}{formatted_body}"
            
            block_tokens = len(block_text) // 4
            
            if current_token_count + block_tokens > self.token_budget:
                if block_idx == 1:
                    max_chars = (self.token_budget - current_token_count) * 4
                    truncated_content = content[:max_chars] + "\n[Truncated due to token budget]"
                    formatted_body = f"```{lang_code}\n{truncated_content}\n```"
                    block_text = f"{header}\n{symbols_line}{section_line}{formatted_body}"
                    context_blocks.append(block_text)
                break
            
            context_blocks.append(block_text)
            current_token_count += block_tokens
            block_idx += 1

        return "\n\n".join(context_blocks) + "\n"


class RetrievalStrategy:
    """Intelligently guides retrieval by analyzing queries and integrating workspace metadata."""

    def __init__(self, query: str, workspace_root: str | Path | None = None) -> None:
        self.query = query
        self.query_lower = query.lower()
        self.workspace_root = Path(workspace_root or os.getcwd()).resolve()

        # Strategy parameters to be computed
        self.limit = 5
        self.prioritized_types: list[str] = []
        self.prioritized_paths: set[str] = set()
        self.prioritized_symbols: set[str] = set()
        self.code_preferred = True

        self.snapshot_files: list[str] = []
        self.test_files: list[str] = []
        self.symbols: list[dict[str, Any]] = []
        self.dependencies: dict[str, list[str]] = {}

        # Load workspace understanding
        self._load_workspace_metadata()
        self._compute_strategy()

    def _load_workspace_metadata(self) -> None:
        """Load snapshot, symbol index, and dependency graph if available."""
        workspace_dir = self.workspace_root / ".workspace"
        
        # 1. Load workspace snapshot
        snapshot_path = workspace_dir / "workspace_snapshot.json"
        if snapshot_path.exists():
            try:
                with open(snapshot_path, encoding="utf-8") as f:
                    data = json.load(f)
                    self.snapshot_files = data.get("files", [])
                    self.test_files = data.get("tests", {}).get("files", [])
            except Exception as e:
                logger.debug(f"Failed to load workspace snapshot: {e}")

        # 2. Load symbol index
        symbol_index_path = workspace_dir / "symbol_index.json"
        if symbol_index_path.exists():
            try:
                with open(symbol_index_path, encoding="utf-8") as f:
                    data = json.load(f)
                    self.symbols = data.get("symbols", [])
            except Exception as e:
                logger.debug(f"Failed to load symbol index: {e}")

        # 3. Load dependency graph
        graph_path = workspace_dir / "dependency_graph.json"
        if graph_path.exists():
            try:
                with open(graph_path, encoding="utf-8") as f:
                    data = json.load(f)
                    nodes = data.get("nodes", [])
                    links = data.get("links", [])
                    for link in links:
                        u = link.get("source")
                        v = link.get("target")
                        if isinstance(u, int) and u < len(nodes):
                            u = nodes[u].get("id")
                        if isinstance(v, int) and v < len(nodes):
                            v = nodes[v].get("id")
                        if isinstance(u, str) and isinstance(v, str):
                            self.dependencies.setdefault(u, []).append(v)
                            self.dependencies.setdefault(v, []).append(u)
            except Exception as e:
                logger.debug(f"Failed to load dependency graph: {e}")

    def _compute_strategy(self) -> None:
        """Analyze query keywords and workspace data to compute priority rules."""
        words = set(re.findall(r"\w+", self.query_lower))

        # 1. Determine base document/source types and limit
        self.limit = 5

        # Check if query requests tests
        if any(w in words for w in ("test", "tests", "assert", "testing")):
            self.prioritized_types.append("test")
            self.code_preferred = True
            self.limit = 10
        
        # Check if query asks for verification
        if "verification" in words or "verify" in words:
            self.prioritized_types.extend(["test", "python_source", "verification_report", "evidence_store"])
            self.limit = 10

        # Check if query requests memory/history/experience
        if any(w in words for w in ("retry", "memory", "experience", "history", "learning", "successful")):
            self.prioritized_types.extend(["retry_memory", "evidence_store", "verification_report"])
            self.limit = 10

        # Check if query asks for design, documentation, architecture, explain, how does it work
        if any(w in words for w in ("documentation", "doc", "docs", "design", "explain", "readme", "architecture", "understand")):
            self.prioritized_types.extend(["readme", "documentation", "markdown", "architectural_summary"])
            self.code_preferred = False
            self.limit = 8

        # 2. File matching: find snapshot files that match query words
        matched_files = []
        for file_path in self.snapshot_files:
            file_stem = Path(file_path).name.lower()
            # If the filename or stem matches query terms, prioritize it
            if file_stem in words or any(w in file_stem for w in words if len(w) > 3):
                matched_files.append(file_path)
                self.prioritized_paths.add(file_path)

        # 3. Symbol matching: find symbols in query words
        for sym in self.symbols:
            sym_name = sym.get("name", "")
            sym_name_lower = sym_name.lower()
            if sym_name_lower in words:
                self.prioritized_symbols.add(sym_name)
                sym_file = sym.get("file")
                if sym_file:
                    self.prioritized_paths.add(sym_file)
                    matched_files.append(sym_file)

        # 4. Dependency graph expansion: for each matched file, check related files
        for f in list(matched_files):
            related = self.dependencies.get(f, [])
            for r in related:
                if "/" in r or r.endswith(".py") or r.endswith(".md"):
                    self.prioritized_paths.add(r)


def summarize_chunk_content(content: str, source_type: str) -> str:
    """Summarize the content of a chunk for the planner context."""
    lines = content.splitlines()
    if not lines:
        return ""
    
    if source_type in ("python_source", "test"):
        defs = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(("def ", "class ", "async def ")):
                defs.append(stripped.rstrip(":"))
        if defs:
            summary = "Contains definitions:\n" + "\n".join(f"- {d}" for d in defs[:5])
            if len(defs) > 5:
                summary += f"\n- ... and {len(defs) - 5} more definitions"
            preview = "\n".join(lines[:5])
            summary += f"\n\nSnippet preview:\n{preview}"
            return summary
        else:
            return "\n".join(lines[:8])
    else:
        non_empty = [l.strip() for l in lines if l.strip()]
        return "\n".join(non_empty[:8])


def format_planner_knowledge_context(results: list[RetrievalResult]) -> str:
    """Format retrieval results as Planner Knowledge Context."""
    if not results:
        return "### Relevant Repository Knowledge\n\nNo relevant repository knowledge retrieved.\n"
    
    blocks = ["### Relevant Repository Knowledge\n"]
    for r in results:
        source_file = os.path.basename(r.source_path) if not r.source_path.startswith("memory://") else r.source_path
        summary = summarize_chunk_content(r.content, r.source_type)
        blocks.append(
            f"Source:\n{source_file}\n\n"
            f"Relevance Score: {r.score:.2f}\n\n"
            f"Summarized Content:\n{summary}"
        )
    return "\n\n".join(blocks) + "\n"


class Retriever:
    """Retrieves relevant document chunks, runs BGE-Reranker, filters results, and tracks retrieval analytics."""

    def __init__(self, vector_store: VectorStore) -> None:
        self.vector_store = vector_store
        self.reranker = BGEReranker()
        self.analytics_history: list[RetrievalAnalytics] = []

    def retrieve(self, query: str, limit: int = 5) -> list[RetrievalResult]:
        """Query vector database, rerank with BGE-Reranker, and return top limit results."""
        start_time = time.perf_counter()
        try:
            workspace = str(self.vector_store.db_path).split("/.rag")[0]
            strategy = RetrievalStrategy(query, workspace_root=workspace)
            
            fetch_limit = max(30, strategy.limit * 3)
            candidates = self.vector_store.search(query, limit=fetch_limit)
            if not candidates:
                self._record_analytics(query, start_time, [], [])
                return []

            reranked = self.reranker.rerank(query, candidates)
            
            boosted = []
            for chunk, score in reranked:
                final_score = score
                
                if chunk.source_path in strategy.prioritized_paths or any(
                    chunk.source_path.endswith(p) for p in strategy.prioritized_paths
                ):
                    final_score += 0.25
                
                if chunk.source_type in strategy.prioritized_types:
                    final_score += 0.15
                    
                chunk_symbols = str(chunk.metadata.get("symbol_names", chunk.metadata.get("symbols", ""))).split(",")
                chunk_symbols = [s.strip() for s in chunk_symbols if s.strip()]
                if any(sym in strategy.prioritized_symbols for sym in chunk_symbols):
                    final_score += 0.20
                    
                if strategy.code_preferred and chunk.source_type in ("python_source", "test"):
                    final_score += 0.10
                elif not strategy.code_preferred and chunk.source_type in ("documentation", "readme", "markdown", "architectural_summary"):
                    final_score += 0.10
                    
                boosted.append((chunk, final_score))
                
            boosted.sort(key=lambda x: x[1], reverse=True)
            
            results = []
            for chunk, score in boosted:
                results.append(
                    RetrievalResult(
                        content=chunk.content,
                        source_path=chunk.source_path,
                        source_type=chunk.source_type,
                        score=score,
                        metadata=chunk.metadata,
                    )
                )

            actual_limit = limit if limit != 5 else strategy.limit
            final_results = results[:actual_limit]
            self._record_analytics(query, start_time, candidates, final_results)
            return final_results
            
        except Exception as exc:
            logger.warning(f"RAG retrieval query failed: {exc}")
            self._record_analytics(query, start_time, [], [])
            return []

    def retrieve_by_type(self, query: str, source_type: str, limit: int = 5) -> list[RetrievalResult]:
        """Perform search query on vector store and filter results to match the specified source_type."""
        filters = {"source_type": source_type}
        return self.retrieve_with_filters(query, filters, limit=limit)

    def retrieve_with_filters(self, query: str, filters: dict[str, Any], limit: int = 5) -> list[RetrievalResult]:
        """Perform search query applying metadata filters on source type, path, category, or symbol name."""
        start_time = time.perf_counter()
        try:
            workspace = str(self.vector_store.db_path).split("/.rag")[0]
            strategy = RetrievalStrategy(query, workspace_root=workspace)

            chroma_where = {}
            if "source_type" in filters:
                chroma_where["source_type"] = filters["source_type"]
            elif "type" in filters:
                chroma_where["source_type"] = filters["type"]
                
            if "document_category" in filters:
                chroma_where["document_type"] = filters["document_category"]
            elif "document_type" in filters:
                chroma_where["document_type"] = filters["document_type"]
                
            if "source_path" in filters:
                chroma_where["source_path"] = filters["source_path"]
            elif "path" in filters:
                chroma_where["source_path"] = filters["path"]

            if isinstance(self.vector_store, ChromaVectorStore):
                count = self.vector_store.collection.count()
                n_results = min(50, count)
                if n_results == 0:
                    self._record_analytics(query, start_time, [], [])
                    return []
                
                chroma_res = self.vector_store.collection.query(
                    query_texts=[query],
                    n_results=n_results,
                    where=chroma_where if chroma_where else None
                )
                
                candidates = []
                if chroma_res and "ids" in chroma_res and chroma_res["ids"]:
                    ids = chroma_res["ids"][0]
                    
                    documents_field = chroma_res.get("documents")
                    documents = []
                    if documents_field is not None and len(documents_field) > 0:
                        documents = documents_field[0] or []
                        
                    metadatas_field = chroma_res.get("metadatas")
                    metadatas = []
                    if metadatas_field is not None and len(metadatas_field) > 0:
                        metadatas = metadatas_field[0] or []
                    
                    for i in range(len(ids)):
                        doc_content = str(documents[i]) if i < len(documents) else ""
                        doc_meta = metadatas[i] if i < len(metadatas) else {}
                        if not isinstance(doc_meta, dict):
                            doc_meta = {}
                        
                        source_type_val = doc_meta.get("source_type", "file")
                        source_type = str(source_type_val) if source_type_val is not None else "file"
                        
                        source_path_val = doc_meta.get("source_path", doc_meta.get("path", ""))
                        source_path = str(source_path_val) if source_path_val is not None else ""
                        
                        candidates.append(
                            DocumentChunk(
                                id=ids[i],
                                source_type=source_type,
                                source_path=source_path,
                                content=doc_content,
                                metadata=doc_meta,
                            )
                        )
            else:
                candidates = self.vector_store.search(query, limit=50)

            filtered_candidates = []
            for chunk in candidates:
                keep = True
                
                if "source_type" in filters and chunk.source_type != filters["source_type"]:
                    keep = False
                elif "type" in filters and chunk.source_type != filters["type"]:
                    keep = False
                    
                if "document_category" in filters and chunk.metadata.get("document_type") != filters["document_category"]:
                    keep = False
                elif "document_type" in filters and chunk.metadata.get("document_type") != filters["document_type"]:
                    keep = False

                if "source_path" in filters and filters["source_path"] not in chunk.source_path:
                    keep = False
                elif "path" in filters and filters["path"] not in chunk.source_path:
                    keep = False
                    
                if "symbol_name" in filters:
                    sym_query = filters["symbol_name"].lower()
                    symbols = str(chunk.metadata.get("symbol_names", chunk.metadata.get("symbols", ""))).lower()
                    if sym_query not in symbols:
                        keep = False
                        
                if keep:
                    filtered_candidates.append(chunk)

            if not filtered_candidates:
                self._record_analytics(query, start_time, [], [])
                return []

            reranked = self.reranker.rerank(query, filtered_candidates)
            
            boosted = []
            for chunk, score in reranked:
                final_score = score
                if chunk.source_path in strategy.prioritized_paths or any(
                    chunk.source_path.endswith(p) for p in strategy.prioritized_paths
                ):
                    final_score += 0.25
                if chunk.source_type in strategy.prioritized_types:
                    final_score += 0.15
                chunk_symbols = str(chunk.metadata.get("symbol_names", chunk.metadata.get("symbols", ""))).split(",")
                chunk_symbols = [s.strip() for s in chunk_symbols if s.strip()]
                if any(sym in strategy.prioritized_symbols for sym in chunk_symbols):
                    final_score += 0.20
                if strategy.code_preferred and chunk.source_type in ("python_source", "test"):
                    final_score += 0.10
                elif not strategy.code_preferred and chunk.source_type in ("documentation", "readme", "markdown", "architectural_summary"):
                    final_score += 0.10
                boosted.append((chunk, final_score))

            boosted.sort(key=lambda x: x[1], reverse=True)

            results: list[RetrievalResult] = []
            for chunk, score in boosted:
                results.append(
                    RetrievalResult(
                        content=chunk.content,
                        source_path=chunk.source_path,
                        source_type=chunk.source_type,
                        score=score,
                        metadata=chunk.metadata,
                    )
                )

            final_results = results[:limit]
            self._record_analytics(query, start_time, filtered_candidates, final_results)
            return final_results

        except Exception as exc:
            logger.warning(f"RAG retrieval query with filters failed: {exc}")
            self._record_analytics(query, start_time, [], [])
            return []

    def retrieve_formatted_context(self, query: str, limit: int = 5) -> str:
        """Helper to get, assemble, and format retrieved context as Markdown for prompts."""
        results = self.retrieve(query, limit=limit)
        workspace = str(self.vector_store.db_path).split("/.rag")[0]
        assembler = ContextAssembler(workspace_root=workspace)
        return assembler.assemble(results)

    def retrieve_planner_context(self, query: str, limit: int = 5) -> str:
        """Retrieve context and format it as Planner Knowledge Context."""
        results = self.retrieve(query, limit=limit)
        return format_planner_knowledge_context(results)

    def _record_analytics(
        self,
        query: str,
        start_time: float,
        raw_candidates: list[DocumentChunk],
        final_results: list[RetrievalResult]
    ) -> None:
        """Build and record statistics of this retrieval turn."""
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        
        res_list = []
        for r in final_results:
            res_list.append({
                "path": r.source_path,
                "type": r.source_type,
                "score": r.score,
            })
            
        analytics = RetrievalAnalytics(
            query=query,
            latency_ms=latency_ms,
            total_raw_results=len(raw_candidates),
            total_final_results=len(final_results),
            results=res_list,
        )
        self.analytics_history.append(analytics)
        
        logger.info(
            f"RAG Retrieval Turn Stats: "
            f"query='{query[:30]}...', "
            f"latency={latency_ms:.2f}ms, "
            f"raw_matches={len(raw_candidates)}, "
            f"final_matches={len(final_results)}"
        )


class RepositoryKnowledgeService:
    """Provides high-level repository search, implementation, test, and relation lookup."""

    def __init__(self, retriever: Retriever | None = None, workspace_root: str | None = None) -> None:
        self.workspace_root = Path(workspace_root or os.getcwd()).resolve()
        if retriever is None:
            from nakama_kun.rag import get_retriever
            self.retriever = get_retriever(str(self.workspace_root))
        else:
            self.retriever = retriever

    def ask_repository(self, question: str) -> list[RetrievalResult]:
        """Perform semantic search on repository knowledge with smart routing."""
        if not self.retriever:
            return []
        return self.retriever.retrieve(question, limit=10)

    def find_implementation(self, topic: str) -> list[RetrievalResult]:
        """Retrieve code chunks implementing a specific topic."""
        if not self.retriever:
            return []
        return self.retriever.retrieve_with_filters(topic, {"source_type": "python_source"}, limit=5)

    def find_tests_for_component(self, component: str) -> list[RetrievalResult]:
        """Find tests associated with a component."""
        if not self.retriever:
            return []
        return self.retriever.retrieve_with_filters(component, {"source_type": "test"}, limit=5)

    def find_related_files(self, file_path: str) -> list[str]:
        """Find related files using the dependency graph and workspace analysis."""
        from nakama_kun.workspace.impact_analyzer import ImpactAnalyzer
        analyzer = ImpactAnalyzer(self.workspace_root)
        try:
            analyzer.load_or_rebuild_graph()
        except Exception:
            return []

        norm_path = file_path
        try:
            norm_path = str(Path(file_path).resolve().relative_to(self.workspace_root))
        except Exception:
            if norm_path.startswith("./") or norm_path.startswith(".\\"):
                norm_path = norm_path[2:]

        related = set()
        if analyzer.graph.has_node(norm_path):
            for succ in analyzer.graph.successors(norm_path):
                if analyzer.graph.nodes[succ].get("type") == "file":
                    related.add(succ)
            for pred in analyzer.graph.predecessors(norm_path):
                if analyzer.graph.nodes[pred].get("type") == "file":
                    related.add(pred)

        base_name = Path(file_path).stem
        if base_name.startswith("test_"):
            comp_name = base_name[5:]
        elif base_name.endswith("_test"):
            comp_name = base_name[:-5]
        else:
            comp_name = base_name

        snapshot_path = self.workspace_root / ".workspace" / "workspace_snapshot.json"
        if snapshot_path.exists():
            try:
                from nakama_kun.workspace.models import ProjectSnapshot
                with open(snapshot_path, encoding="utf-8") as f:
                    snapshot = ProjectSnapshot.model_validate_json(f.read())
                for f_idx in snapshot.files:
                    f_name = Path(f_idx).name
                    if comp_name in f_name:
                        related.add(f_idx)
            except Exception:
                pass

        related.discard(norm_path)
        return sorted(list(related))
