from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import chromadb
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

from nakama_kun.rag.embeddings import EmbeddingProvider


@dataclass
class DocumentChunk:
    """Represents a text chunk of a workspace file or task context with metadata."""
    id: str
    source_type: str
    source_path: str
    content: str
    metadata: dict[str, Any]


@dataclass
class IndexedDocument:
    """Represents a document (file or virtual resource) tracked by the indexer."""
    path: str
    type: str
    chunk_count: int
    indexed_at: str


class ChromaEmbeddingWrapper(EmbeddingFunction[Documents]):
    """Adapter wrapping our custom EmbeddingProvider for use within ChromaDB."""

    def __init__(self, provider: EmbeddingProvider) -> None:
        self.provider = provider

    def __call__(self, input: Documents) -> Embeddings:
        return self.provider.embed_documents(list(input))  # type: ignore


class VectorStore(ABC):
    """Interface defining vector storage operations."""

    @property
    @abstractmethod
    def db_path(self) -> str:
        """The absolute path to the local vector database folder."""
        pass

    @abstractmethod
    def add_chunks(self, chunks: list[DocumentChunk]) -> None:
        """Upsert a list of chunks into the store."""
        pass

    @abstractmethod
    def search(self, query: str, limit: int = 5) -> list[DocumentChunk]:
        """Perform similarity search and return relevant chunks."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Wipe all content from the vector store."""
        pass


class ChromaVectorStore(VectorStore):
    """Local ChromaDB-backed vector database."""

    def __init__(
        self,
        db_path: str,
        collection_name: str = "nakama_workspace",
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._db_path = db_path
        self.collection_name = collection_name
        self.embedding_provider = embedding_provider

        # Setup custom embedding function wrapper if a provider is specified
        self.embedding_function = None
        if embedding_provider is not None:
            self.embedding_function = ChromaEmbeddingWrapper(embedding_provider)

        # Initialize the persistent Chroma client
        self.client = chromadb.PersistentClient(path=db_path)
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=self.embedding_function,  # type: ignore
        )

    @property
    def db_path(self) -> str:
        return self._db_path

    def add_chunks(self, chunks: list[DocumentChunk]) -> None:
        if not chunks:
            return

        ids = [chunk.id for chunk in chunks]
        documents = [chunk.content for chunk in chunks]
        metadatas = []
        for chunk in chunks:
            meta = chunk.metadata.copy()
            meta["source_type"] = chunk.source_type
            meta["source_path"] = chunk.source_path
            metadatas.append(meta)

        # Use upsert to handle updates cleanly
        self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,  # type: ignore
        )

    def search(self, query: str, limit: int = 5) -> list[DocumentChunk]:
        if not query:
            return []

        # Bound retrieval count dynamically to avoid indexing out of bounds
        count = self.collection.count()
        if count == 0:
            return []

        n_results = min(limit, count)

        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
        )

        chunks = []
        if results and "ids" in results and results["ids"]:
            ids = results["ids"][0]
            documents_list = results.get("documents")
            documents = documents_list[0] if documents_list is not None else []
            metadatas_list = results.get("metadatas")
            metadatas = metadatas_list[0] if metadatas_list is not None else []

            for i in range(len(ids)):
                doc_content = documents[i] if i < len(documents) else ""
                doc_meta = metadatas[i] if i < len(metadatas) else {}
                source_type = doc_meta.get("source_type", "file")
                source_path = doc_meta.get("source_path", doc_meta.get("path", ""))
                chunks.append(
                    DocumentChunk(
                        id=ids[i],
                        source_type=source_type,
                        source_path=source_path,
                        content=doc_content,
                        metadata=doc_meta,  # type: ignore
                    )
                )

        return chunks

    def clear(self) -> None:
        import contextlib
        with contextlib.suppress(Exception):
            self.client.delete_collection(self.collection_name)
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=self.embedding_function,  # type: ignore
        )
