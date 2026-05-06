"""
ChromaDB-backed vector store for RAG.

Used by Agent 2 (Validation Agent) to:
  1. Confirm that values extracted by Agent 1 actually appear in the raw document.
  2. Retrieve relevant context when Agent 2 needs to re-check a value.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer

from src.core.document_processor import DocumentChunk

logger = logging.getLogger(__name__)


class VectorStore:
    """
    Thin wrapper around ChromaDB + SentenceTransformers.

    Provides:
      - index_chunks()             : batch-upsert document chunks
      - query()                    : semantic similarity search
      - verify_value_in_document() : RAG-based existence check
    """

    def __init__(
        self,
        persist_dir: str = "outputs/chroma_db",
        collection_name: str = "pharma_compliance_docs",
        embedding_model: str = "all-MiniLM-L6-v2",
    ) -> None:
        logger.info("Initialising VectorStore with model '%s'", embedding_model)
        self._embedder = SentenceTransformer(embedding_model)

        self._client = chromadb.PersistentClient(
            path=persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "VectorStore ready — collection '%s' has %d existing docs",
            collection_name,
            self._collection.count(),
        )

    # ── Public API ────────────────────────────────────────────────────────

    def index_chunks(self, chunks: List[DocumentChunk], batch_size: int = 64) -> None:
        """Embed and upsert document chunks in batches."""
        if not chunks:
            return

        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            texts = [c.content for c in batch]
            embeddings = self._embedder.encode(
                texts, show_progress_bar=False
            )
            self._collection.upsert(
                ids=[c.chunk_id for c in batch],
                documents=texts,
                embeddings=embeddings,  # type: ignore[arg-type]
                metadatas=[c.metadata for c in batch],
            )

        logger.info("Indexed %d chunks into vector store", len(chunks))

    def query(
        self,
        query_text: str,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Semantic similarity search.

        Returns a list of dicts with keys: ``content``, ``metadata``, ``distance``.
        """
        count = self._collection.count()
        if count == 0:
            return []

        n = min(n_results, count)
        query_embedding = self._embedder.encode([query_text]).tolist()

        kwargs: Dict[str, Any] = {
            "query_embeddings": query_embedding,
            "n_results": n,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        results = self._collection.query(**kwargs)

        return [
            {
                "content": doc,
                "metadata": results["metadatas"][0][i],  # type: ignore[index]
                "distance": results["distances"][0][i],  # type: ignore[index]
            }
            for i, doc in enumerate(results["documents"][0])  # type: ignore[index]
        ]

    def verify_value_in_document(
        self, value: str, parameter: str, section: str = ""
    ) -> bool:
        """
        RAG-based verification: check whether ``value`` appears in the context
        retrieved for a given parameter + section query.

        Returns True if the value string is found verbatim in any of the top-3
        retrieved chunks.
        """
        query_text = f"{parameter} {value} {section}".strip()
        try:
            results = self.query(query_text, n_results=3)
            return any(str(value) in r["content"] for r in results)
        except Exception as exc:
            logger.warning("RAG verification failed for '%s=%s': %s", parameter, value, exc)
            return False

    def clear(self) -> None:
        """Drop and recreate the collection (useful for re-indexing)."""
        name = self._collection.name
        self._client.delete_collection(name)
        self._collection = self._client.get_or_create_collection(
            name=name, metadata={"hnsw:space": "cosine"}
        )
        logger.info("Collection '%s' cleared", name)
