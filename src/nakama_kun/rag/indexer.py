from __future__ import annotations

import json
import sqlite3
import re
import math
from pathlib import Path
from datetime import datetime, UTC
from loguru import logger

from nakama_kun.rag.vector_store import DocumentChunk, IndexedDocument, VectorStore, ChromaVectorStore
from nakama_kun.workspace.analyzer import WorkspaceAnalyzer
from nakama_kun.workspace.scanner import DirectoryScanner


class DocumentMetadataStore:
    """SQLite-backed metadata store for keeping track of indexed documents."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS indexed_documents (
                    path TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL,
                    indexed_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def save_document(self, doc: IndexedDocument) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO indexed_documents (path, type, chunk_count, indexed_at)
                VALUES (?, ?, ?, ?)
                """,
                (doc.path, doc.type, doc.chunk_count, doc.indexed_at)
            )
            conn.commit()

    def get_document(self, path: str) -> IndexedDocument | None:
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.execute(
                    "SELECT path, type, chunk_count, indexed_at FROM indexed_documents WHERE path = ?",
                    (path,)
                )
                row = cursor.fetchone()
                if row:
                    return IndexedDocument(path=row[0], type=row[1], chunk_count=row[2], indexed_at=row[3])
        except Exception:
            pass
        return None

    def delete_document(self, path: str) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("DELETE FROM indexed_documents WHERE path = ?", (path,))
            conn.commit()

    def list_documents(self) -> list[IndexedDocument]:
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.execute("SELECT path, type, chunk_count, indexed_at FROM indexed_documents")
                return [
                    IndexedDocument(path=row[0], type=row[1], chunk_count=row[2], indexed_at=row[3])
                    for row in cursor.fetchall()
                ]
        except Exception:
            return []

    def clear(self) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("DELETE FROM indexed_documents")
            conn.commit()


class IndexMetadataManager:
    """Manages index execution statistics in a JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save(self, metadata: dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to save index metadata: {e}")


def fetch_memory_sources(db_path: Path) -> list[dict[str, Any]]:
    """Fetch virtual memory records from nakama_memory.db sqlite tables."""
    sources = []
    if not db_path.exists():
        return sources

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # 1. Project summaries -> workspace_summary
        try:
            cursor = conn.execute("SELECT project_name, summary, analyzed_at FROM project_summaries")
            for row in cursor.fetchall():
                sources.append({
                    "path": f"memory://project_summaries/{row['project_name']}",
                    "type": "workspace_summary",
                    "content": row["summary"],
                    "timestamp": row["analyzed_at"],
                    "is_virtual": True,
                })
        except Exception as e:
            logger.warning(f"Error fetching project_summaries: {e}")

        # 2. Failure records -> retry_memory and verification_report
        try:
            cursor = conn.execute("SELECT id, goal, attempted_actions, failure_type, failure_message, resolution, timestamp, failure_frequency FROM failure_records")
            for row in cursor.fetchall():
                # Retry memory content
                retry_content = (
                    f"Goal: {row['goal']}\n"
                    f"Failure Type: {row['failure_type']}\n"
                    f"Attempted Actions: {row['attempted_actions']}\n"
                    f"Failure Message: {row['failure_message']}\n"
                    f"Resolution: {row['resolution']}\n"
                    f"Failure Frequency: {row['failure_frequency']}"
                )
                sources.append({
                    "path": f"memory://failure_records/{row['id']}",
                    "type": "retry_memory",
                    "content": retry_content,
                    "timestamp": row["timestamp"],
                    "is_virtual": True,
                })

                # Verification report content
                verif_content = (
                    f"Verification Report for Task: {row['goal']}\n"
                    f"Failure Type: {row['failure_type']}\n"
                    f"Error Details:\n{row['failure_message']}\n"
                    f"Resolution Strategy: {row['resolution']}"
                )
                sources.append({
                    "path": f"memory://verification_reports/{row['id']}",
                    "type": "verification_report",
                    "content": verif_content,
                    "timestamp": row["timestamp"],
                    "is_virtual": True,
                })
        except Exception as e:
            logger.warning(f"Error fetching failure_records: {e}")

        # 3. Successful tasks -> evidence_store
        try:
            cursor = conn.execute("SELECT id, goal, plan_summary, files_changed, tools_used, outcome, timestamp, success_frequency FROM successful_tasks")
            for row in cursor.fetchall():
                evidence_content = (
                    f"Goal: {row['goal']}\n"
                    f"Plan Summary: {row['plan_summary']}\n"
                    f"Files Changed: {row['files_changed']}\n"
                    f"Tools Used: {row['tools_used']}\n"
                    f"Outcome: {row['outcome']}\n"
                    f"Success Frequency: {row['success_frequency']}"
                )
                sources.append({
                    "path": f"memory://successful_tasks/{row['id']}",
                    "type": "evidence_store",
                    "content": evidence_content,
                    "timestamp": row["timestamp"],
                    "is_virtual": True,
                })
        except Exception as e:
            logger.warning(f"Error fetching successful_tasks: {e}")

        conn.close()
    except Exception as e:
        logger.warning(f"Error connecting to memory DB: {e}")

    return sources


def chunk_text(
    content: str,
    source_path: str,
    source_type: str,
    symbol_extractor: callable = None,
    metadata_base: dict = None
) -> list[DocumentChunk]:
    """Split text content into chunks of 800-1200 characters with 100-200 characters overlap.

    Preserves: file path, symbol names, document type, section title.
    """
    if metadata_base is None:
        metadata_base = {}

    chunks = []
    lines = content.splitlines()

    current_chunk_lines = []
    current_chunk_len = 0
    start_line = 1
    last_section_title = ""

    i = 0
    num_lines = len(lines)

    while i < num_lines:
        line = lines[i]
        line_len = len(line) + 1  # plus newline character

        # Track Markdown sections
        is_heading = False
        heading_title = ""
        if source_type in ("markdown", "readme", "architectural_summary"):
            if line.startswith("#"):
                match = re.match(r"^#+\s+(.+)$", line)
                if match:
                    is_heading = True
                    heading_title = match.group(1).strip()

        # If it is a heading, and we already have some content, split before the heading
        if is_heading and current_chunk_len > 0:
            chunk_content = "\n".join(current_chunk_lines)
            end_line = i
            symbols = ""
            if symbol_extractor:
                symbols = ", ".join(symbol_extractor(current_chunk_lines, source_type))
            meta = metadata_base.copy()
            meta.update({
                "path": source_path,
                "document_type": source_type,
                "section_title": last_section_title,
                "symbol_names": symbols,
                "line_start": start_line,
                "line_end": end_line,
            })
            chunk_id = f"{source_path}:{start_line}-{end_line}"
            chunks.append(DocumentChunk(
                id=chunk_id,
                source_type=source_type,
                source_path=source_path,
                content=chunk_content,
                metadata=meta
            ))
            current_chunk_lines = []
            current_chunk_len = 0
            start_line = i + 1

        # Check if adding this line would exceed the upper bound (1200 characters)
        if current_chunk_len + line_len > 1200:
            if current_chunk_len >= 800:
                # Package current buffer
                chunk_content = "\n".join(current_chunk_lines)
                end_line = i

                # Extract symbols
                symbols = ""
                if symbol_extractor:
                    symbols = ", ".join(symbol_extractor(current_chunk_lines, source_type))

                meta = metadata_base.copy()
                meta.update({
                    "path": source_path,
                    "document_type": source_type,
                    "section_title": last_section_title,
                    "symbol_names": symbols,
                    "line_start": start_line,
                    "line_end": end_line,
                })

                chunk_id = f"{source_path}:{start_line}-{end_line}"
                chunks.append(DocumentChunk(
                    id=chunk_id,
                    source_type=source_type,
                    source_path=source_path,
                    content=chunk_content,
                    metadata=meta
                ))

                # Backtrack lines for overlap (100-200 characters)
                overlap_len = 0
                backtrack_lines = 0
                for j in range(len(current_chunk_lines) - 1, -1, -1):
                    l_len = len(current_chunk_lines[j]) + 1
                    if overlap_len + l_len > 200:
                        break
                    overlap_len += l_len
                    backtrack_lines += 1
                    if overlap_len >= 100:
                        break

                if backtrack_lines > 0:
                    current_chunk_lines = current_chunk_lines[-backtrack_lines:]
                    current_chunk_len = overlap_len
                    start_line = i - backtrack_lines + 1
                else:
                    current_chunk_lines = []
                    current_chunk_len = 0
                    start_line = i + 1
            else:
                # Handle long lines or files with very long single lines
                if current_chunk_len == 0:
                    start_char = 0
                    line_text = line
                    while start_char < len(line_text):
                        end_char = min(start_char + 1000, len(line_text))
                        sliced_content = line_text[start_char:end_char]
                        meta = metadata_base.copy()
                        meta.update({
                            "path": source_path,
                            "document_type": source_type,
                            "section_title": last_section_title,
                            "symbol_names": "",
                            "line_start": i + 1,
                            "line_end": i + 1,
                        })
                        chunk_id = f"{source_path}:{i+1}-char_{start_char}"
                        chunks.append(DocumentChunk(
                            id=chunk_id,
                            source_type=source_type,
                            source_path=source_path,
                            content=sliced_content,
                            metadata=meta
                        ))
                        if end_char == len(line_text):
                            break
                        start_char += 850  # overlap ~150 chars
                    i += 1
                    start_line = i + 1
                else:
                    chunk_content = "\n".join(current_chunk_lines)
                    end_line = i
                    symbols = ""
                    if symbol_extractor:
                        symbols = ", ".join(symbol_extractor(current_chunk_lines, source_type))
                    meta = metadata_base.copy()
                    meta.update({
                        "path": source_path,
                        "document_type": source_type,
                        "section_title": last_section_title,
                        "symbol_names": symbols,
                        "line_start": start_line,
                        "line_end": end_line,
                    })
                    chunk_id = f"{source_path}:{start_line}-{end_line}"
                    chunks.append(DocumentChunk(
                        id=chunk_id,
                        source_type=source_type,
                        source_path=source_path,
                        content=chunk_content,
                        metadata=meta
                    ))
                    current_chunk_lines = []
                    current_chunk_len = 0
                    start_line = i + 1
        else:
            if is_heading:
                last_section_title = heading_title
            current_chunk_lines.append(line)
            current_chunk_len += line_len
            i += 1

    if current_chunk_lines:
        chunk_content = "\n".join(current_chunk_lines)
        end_line = num_lines
        symbols = ""
        if symbol_extractor:
            symbols = ", ".join(symbol_extractor(current_chunk_lines, source_type))
        meta = metadata_base.copy()
        meta.update({
            "path": source_path,
            "document_type": source_type,
            "section_title": last_section_title,
            "symbol_names": symbols,
            "line_start": start_line,
            "line_end": end_line,
        })
        chunk_id = f"{source_path}:{start_line}-{end_line}"
        chunks.append(DocumentChunk(
            id=chunk_id,
            source_type=source_type,
            source_path=source_path,
            content=chunk_content,
            metadata=meta
        ))

    return chunks


class Indexer:
    """Orchestrates workspace scanning, character-based chunking, metadata persistence, and incremental vector database updates."""

    def __init__(
        self,
        workspace_root: str,
        vector_store: VectorStore,
        chunk_size_lines: int = 50,  # kept for signature compatibility
        chunk_overlap_lines: int = 10,  # kept for signature compatibility
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.vector_store = vector_store
        
        self.rag_dir = self.workspace_root / ".rag"
        self.chroma_dir = self.rag_dir / "chroma"
        self.sqlite_db_path = self.rag_dir / "documents.db"
        self.metadata_path = self.rag_dir / "index_metadata.json"

        # Initialize folders & DB
        self.rag_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        
        self.metadata_store = DocumentMetadataStore(self.sqlite_db_path)
        self.metadata_manager = IndexMetadataManager(self.metadata_path)
        self.scanner = DirectoryScanner(self.workspace_root)

        # Supported text extensions
        self.extension_map = WorkspaceAnalyzer.EXTENSION_MAP

        # Regex symbol pattern matcher
        self.symbol_patterns = {
            "python_source": re.compile(r"^\s*(def|class)\s+(\w+)"),
            "test": re.compile(r"^\s*(def|class)\s+(\w+)"),
            "markdown": re.compile(r"^#{1,3}\s+(.+)$"),
            "readme": re.compile(r"^#{1,3}\s+(.+)$"),
            "architectural_summary": re.compile(r"^#{1,3}\s+(.+)$"),
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

    def _collect_all_sources(self) -> list[dict[str, Any]]:
        """Scans the physical workspace and queries database memory events to build active sources list."""
        sources = []

        # 1. Scan physical workspace files
        scan_result = self.scanner.scan()
        for f in scan_result.files:
            abs_path = self.workspace_root / f.path
            if self.is_binary(abs_path) or self.is_secret_file(f.path):
                continue

            # Determine source type
            name_lower = f.name.lower()
            ext = f.extension.lower()

            if name_lower.startswith("readme"):
                source_type = "readme"
            elif f.path.startswith("docs/") or ext in (".txt", ".rst"):
                source_type = "documentation"
            elif f.path.startswith("tests/") or name_lower.startswith("test_") or name_lower.endswith("_test.py"):
                source_type = "test"
            elif ext == ".py":
                source_type = "python_source"
            elif ext == ".md":
                source_type = "markdown"
            else:
                continue

            sources.append({
                "path": f.path,
                "type": source_type,
                "timestamp": f.modified_time.isoformat(),
                "is_virtual": False,
            })

        # 2. Architectural summary
        arch_path = self.workspace_root / ".workspace" / "architecture_summary.md"
        if arch_path.exists() and arch_path.is_file():
            stat = arch_path.stat()
            mtime_dt = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
            sources.append({
                "path": ".workspace/architecture_summary.md",
                "type": "architectural_summary",
                "timestamp": mtime_dt.isoformat(),
                "is_virtual": False,
            })

        # 3. Database memory sources
        db_path = self.workspace_root / "nakama_memory.db"
        db_sources = fetch_memory_sources(db_path)
        sources.extend(db_sources)

        return sources

    def _chunk_source(self, src: dict[str, Any]) -> list[DocumentChunk]:
        """Reads and chunks a source dictionary."""
        path = src["path"]
        source_type = src["type"]
        is_virtual = src.get("is_virtual", True) if "is_virtual" in src else path.startswith("memory://")

        if is_virtual:
            content = src["content"]
        else:
            abs_path = self.workspace_root / path
            if not abs_path.exists() or not abs_path.is_file():
                return []
            try:
                try:
                    content = abs_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    content = abs_path.read_text(encoding="latin-1")
            except Exception as e:
                logger.warning(f"Failed to read file {path}: {e}")
                return []

        def extract_symbols(lines: list[str], lang: str) -> list[str]:
            pattern = self.symbol_patterns.get(lang)
            if not pattern:
                return []
            symbols = []
            for line in lines:
                match = pattern.search(line)
                if match:
                    groups = [g for g in match.groups() if g]
                    if len(groups) >= 2:
                        symbols.append(groups[1])
                    elif len(groups) == 1:
                        symbols.append(groups[0])
            return symbols[:10]

        return chunk_text(
            content=content,
            source_path=path,
            source_type=source_type,
            symbol_extractor=extract_symbols,
            metadata_base={"mtime": src["timestamp"]}
        )

    def fetch_task_chunks(self) -> list[DocumentChunk]:
        """Kept for tests / backward compatibility."""
        return []

    def build(self) -> None:
        """Complete clean build of the vector store index."""
        logger.info("Starting clean RAG index build...")

        # Clear vector store and sqlite metadata store
        self.vector_store.clear()
        self.metadata_store.clear()

        # 1. Collect all sources
        sources = self._collect_all_sources()

        # 2. Process all sources
        all_chunks = []
        for src in sources:
            chunks = self._chunk_source(src)
            if chunks:
                all_chunks.extend(chunks)

                # Save metadata record
                doc = IndexedDocument(
                    path=src["path"],
                    type=src["type"],
                    chunk_count=len(chunks),
                    indexed_at=datetime.now(UTC).isoformat()
                )
                self.metadata_store.save_document(doc)

        # 3. Add to vector store
        if all_chunks:
            self.vector_store.add_chunks(all_chunks)

        # 4. Save metadata json
        meta = {
            "last_indexed_at": datetime.now(UTC).isoformat(),
            "total_documents": len(sources),
            "total_chunks": len(all_chunks),
            "embedding_model": "BGE-M3",
        }
        self.metadata_manager.save(meta)

        logger.info(f"RAG index build complete. Indexed {len(sources)} documents with {len(all_chunks)} chunks.")

    def refresh(self) -> None:
        """Incremental refresh: syncs file changes on disk and memory database events."""
        logger.info("Starting incremental RAG index refresh...")

        # Retrieve currently indexed documents from documents.db
        indexed_docs = {doc.path: doc for doc in self.metadata_store.list_documents()}

        # Collect active sources
        active_sources = self._collect_all_sources()
        active_paths = {src["path"] for src in active_sources}

        # 1. Identify deleted documents
        deleted_paths = [path for path in indexed_docs if path not in active_paths]
        for path in deleted_paths:
            logger.info(f"Removing deleted document from RAG index: {path}")
            if isinstance(self.vector_store, ChromaVectorStore):
                self.vector_store.collection.delete(where={"source_path": path})
            self.metadata_store.delete_document(path)

        # 2. Identify modified or new documents
        new_or_modified_sources = []
        for src in active_sources:
            path = src["path"]
            mtime_str = src["timestamp"]

            doc_meta = indexed_docs.get(path)
            if doc_meta is None:
                new_or_modified_sources.append(src)
            else:
                if mtime_str > doc_meta.indexed_at:
                    logger.info(f"Document modified: {path} (src: {mtime_str}, indexed: {doc_meta.indexed_at})")
                    if isinstance(self.vector_store, ChromaVectorStore):
                        self.vector_store.collection.delete(where={"source_path": path})
                    new_or_modified_sources.append(src)

        # 3. Chunk and process modifications/additions
        updated_chunks = []
        for src in new_or_modified_sources:
            chunks = self._chunk_source(src)
            if chunks:
                updated_chunks.extend(chunks)
                doc = IndexedDocument(
                    path=src["path"],
                    type=src["type"],
                    chunk_count=len(chunks),
                    indexed_at=datetime.now(UTC).isoformat()
                )
                self.metadata_store.save_document(doc)
            else:
                self.metadata_store.delete_document(src["path"])

        # 4. Upsert chunks
        if updated_chunks:
            self.vector_store.add_chunks(updated_chunks)

        # 5. Update metadata json
        all_docs = self.metadata_store.list_documents()
        total_chunks = sum(doc.chunk_count for doc in all_docs)
        meta = {
            "last_indexed_at": datetime.now(UTC).isoformat(),
            "total_documents": len(all_docs),
            "total_chunks": total_chunks,
            "embedding_model": "BGE-M3",
        }
        self.metadata_manager.save(meta)

        logger.info(f"RAG index refresh complete. Synchronized {len(new_or_modified_sources)} updated documents. Removed {len(deleted_paths)} deleted documents.")


# Expose RepositoryIndexer alias
RepositoryIndexer = Indexer
