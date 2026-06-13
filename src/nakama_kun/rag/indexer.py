from __future__ import annotations

import re
from pathlib import Path

from loguru import logger

from nakama_kun.rag.vector_store import DocumentChunk, VectorStore
from nakama_kun.workspace.analyzer import WorkspaceAnalyzer
from nakama_kun.workspace.scanner import DirectoryScanner


class Indexer:
    """Orchestrates workspace scanning, chunking, binary/secret filtering, and vector database index updates."""

    def __init__(
        self,
        workspace_root: str,
        vector_store: VectorStore,
        chunk_size_lines: int = 50,
        chunk_overlap_lines: int = 10,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.vector_store = vector_store
        self.chunk_size_lines = chunk_size_lines
        self.chunk_overlap_lines = chunk_overlap_lines
        self.scanner = DirectoryScanner(self.workspace_root)

        # Supported text extensions mapping
        self.extension_map = WorkspaceAnalyzer.EXTENSION_MAP

        # Symbol search patterns per language
        self.symbol_patterns = {
            "Python": re.compile(r"^\s*(def|class)\s+(\w+)"),
            "JavaScript": re.compile(r"^\s*(class|function)\s+(\w+)|const\s+(\w+)\s*=\s*(async\s*)?\("),
            "TypeScript": re.compile(r"^\s*(class|function|interface|type)\s+(\w+)|const\s+(\w+)\s*=\s*(async\s*)?\("),
            "Go": re.compile(r"^\s*func\s+(\([^)]+\)\s*)?(\w+)"),
            "Markdown": re.compile(r"^#{1,3}\s+(.+)$"),
        }

    def is_binary(self, file_path: Path) -> bool:
        """Heuristic check for binary file types using null byte detection."""
        try:
            with open(file_path, "rb") as f:
                block = f.read(4096)
                return b"\x00" in block
        except Exception:
            return True

    def is_secret_file(self, file_path_rel: str) -> bool:
        """Heuristic check to prevent indexing environment configs and secret keys."""
        parts = [p.lower() for p in Path(file_path_rel).parts]
        name = Path(file_path_rel).name.lower()

        if any(k in parts for k in ["secrets", "keys", "credentials", ".agents"]):
            return True

        if Path(file_path_rel).suffix.lower() in [".pem", ".key", ".p12", ".db", ".lock"]:
            return True

        if any(k in name for k in ["secret", "credential", "private", "id_rsa"]):
            return True

        return bool(name.startswith(".env"))

    def extract_symbols(self, lines: list[str], language: str) -> list[str]:
        """Regex-based symbol hint extraction for prompt relevance."""
        pattern = self.symbol_patterns.get(language)
        if not pattern:
            return []

        symbols = []
        for line in lines:
            match = pattern.search(line)
            if match:
                # Extract first non-empty group
                groups = [g for g in match.groups() if g]
                if len(groups) >= 2:
                    symbols.append(groups[1])
                elif len(groups) == 1:
                    symbols.append(groups[0])
        return symbols[:10]  # Cap at 10 symbols per chunk

    def chunk_file(self, file_path_rel: str) -> list[DocumentChunk]:
        """Read, parse, and split a text file into overlapping document chunks."""
        abs_path = self.workspace_root / file_path_rel
        if not abs_path.exists() or not abs_path.is_file():
            return []

        if self.is_binary(abs_path) or self.is_secret_file(file_path_rel):
            return []

        try:
            # Safe read with fallback decoding
            try:
                content = abs_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = abs_path.read_text(encoding="latin-1")
        except Exception as exc:
            logger.warning(f"Failed to read file {file_path_rel} for indexing: {exc}")
            return []

        lines = content.splitlines()
        ext = abs_path.suffix.lower()
        language = self.extension_map.get(ext, "Text")
        mtime = abs_path.stat().st_mtime

        chunks = []
        num_lines = len(lines)
        step = self.chunk_size_lines - self.chunk_overlap_lines
        if step <= 0:
            step = self.chunk_size_lines

        # Slidng window over lines
        i = 0
        while i < num_lines or (num_lines == 0 and i == 0):
            line_start = i + 1
            line_end = min(i + self.chunk_size_lines, num_lines) if num_lines > 0 else 1

            chunk_lines = lines[i:line_end] if num_lines > 0 else [""]
            chunk_content = "\n".join(chunk_lines)

            # Extract symbols for metadata hints
            symbols = self.extract_symbols(chunk_lines, language)

            chunk_id = f"{file_path_rel}:{line_start}-{line_end}"
            metadata = {
                "path": file_path_rel,
                "language": language,
                "line_start": line_start,
                "line_end": line_end,
                "symbols": ", ".join(symbols),
                "mtime": mtime,
                "type": "file",
            }

            chunks.append(DocumentChunk(id=chunk_id, content=chunk_content, metadata=metadata))

            if num_lines == 0 or line_end >= num_lines:
                break
            i += step

        return chunks

    def fetch_task_chunks(self) -> list[DocumentChunk]:
        """Fetch historical tasks from SQLite memory and format them as indexable chunks."""
        chunks = []
        try:
            from nakama_kun.memory import get_memory_repository
            repo = get_memory_repository()
            tasks = repo.list_tasks(limit=1000)

            for t in tasks:
                task_id = t.get("id", "")
                desc = t.get("task_description", "")
                status = t.get("status", "")
                created = t.get("created_at", "")
                finished = t.get("finished_at", "") or "N/A"

                content = (
                    f"[Historical Task]\n"
                    f"Task ID: {task_id}\n"
                    f"Description: {desc}\n"
                    f"Status: {status}\n"
                    f"Created At: {created}\n"
                    f"Finished At: {finished}"
                )

                chunk_id = f"memory://tasks/{task_id}"
                metadata = {
                    "path": f"memory://tasks/{task_id}",
                    "type": "task",
                    "task_id": task_id,
                    "language": "Text",
                    "line_start": 1,
                    "line_end": 6,
                    "mtime": 0.0,
                }
                chunks.append(DocumentChunk(id=chunk_id, content=content, metadata=metadata))
        except Exception as exc:
            logger.warning(f"Could not load memory tasks for indexer: {exc}")

        return chunks

    def build(self) -> None:
        """Complete clean build of the vector store index."""
        logger.info("Starting clean RAG index build...")
        self.vector_store.clear()

        # Scan files
        scan_result = self.scanner.scan()
        all_chunks = []

        for f in scan_result.files:
            file_chunks = self.chunk_file(f.path)
            all_chunks.extend(file_chunks)

        # Retrieve tasks
        task_chunks = self.fetch_task_chunks()
        all_chunks.extend(task_chunks)

        # Upsert in database
        self.vector_store.add_chunks(all_chunks)
        logger.info(f"RAG index build complete. Indexed {len(all_chunks)} chunks.")

    def refresh(self) -> None:
        """Incremental refresh: syncs file changes on disk and deletes stale chunks."""
        logger.info("Starting incremental RAG index refresh...")

        # 1. Fetch current vector store metadatas to build a status map
        stored_files: dict[str, float] = {}
        try:
            # Accessing chroma collection directly via helper
            from nakama_kun.rag.vector_store import ChromaVectorStore
            if isinstance(self.vector_store, ChromaVectorStore):
                collection_data = self.vector_store.collection.get(include=["metadatas"])
                metadatas = collection_data.get("metadatas", []) or []
                for meta in metadatas:
                    if meta and "path" in meta and meta.get("type") == "file":
                        path = meta["path"]
                        mtime = meta.get("mtime", 0.0)
                        if isinstance(path, str) and isinstance(mtime, (int, float)):
                            stored_files[path] = max(stored_files.get(path, 0.0), float(mtime))
        except Exception as exc:
            logger.warning(f"Could not read existing RAG index for refresh (performing clean rebuild): {exc}")
            self.build()
            return

        # 2. Scan active workspace files
        scan_result = self.scanner.scan()
        active_paths = {f.path for f in scan_result.files}

        # 3. Identify files to delete (stored in DB but no longer present in active scan)
        deleted_files = [path for path in stored_files if path not in active_paths]
        for path in deleted_files:
            logger.info(f"Removing deleted file from RAG index: {path}")
            if isinstance(self.vector_store, ChromaVectorStore):
                self.vector_store.collection.delete(where={"path": path})

        # 4. Identify modified/new files
        files_to_index = []
        for f in scan_result.files:
            # Skip binary and secret files early
            abs_path = self.workspace_root / f.path
            if self.is_binary(abs_path) or self.is_secret_file(f.path):
                continue

            current_mtime = f.modified_time.timestamp()
            stored_mtime = stored_files.get(f.path)

            if stored_mtime is None:
                # New file
                files_to_index.append(f.path)
            elif abs(current_mtime - stored_mtime) > 1e-3:
                # Modified file
                logger.info(f"File modified on disk: {f.path}")
                # Delete existing chunks first
                if isinstance(self.vector_store, ChromaVectorStore):
                    self.vector_store.collection.delete(where={"path": f.path})
                files_to_index.append(f.path)

        # 5. Index updated files
        updated_chunks = []
        for path in files_to_index:
            logger.info(f"Indexing file: {path}")
            updated_chunks.extend(self.chunk_file(path))

        if updated_chunks:
            self.vector_store.add_chunks(updated_chunks)

        # 6. Always refresh tasks cleanly
        if isinstance(self.vector_store, ChromaVectorStore):
            import contextlib
            with contextlib.suppress(Exception):
                self.vector_store.collection.delete(where={"type": "task"})
        task_chunks = self.fetch_task_chunks()
        self.vector_store.add_chunks(task_chunks)

        logger.info(f"RAG index refresh complete. Updated/added {len(updated_chunks) + len(task_chunks)} chunks.")
