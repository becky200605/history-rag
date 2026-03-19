from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client import models

from src.community.knowledge_base.common import get_thread_collection_name
from src.community.knowledge_base.lexical_search import lexical_search_documents
from src.config.knowledge_base_config import get_knowledge_base_config
from src.reflection import resolve_variable

"""
Module for retrieving documents from the knowledge base using Qdrant.
"""

_retriever_instance = None


def get_embedding_model() -> Embeddings:
    """Get the embedding model based on configuration."""
    config = get_knowledge_base_config()
    if not config.embedding:
        raise ValueError("Embedding configuration is missing")

    kwargs = {}
    if config.embedding.api_key:
        kwargs["api_key"] = config.embedding.api_key
    if config.embedding.api_base:
        kwargs["base_url"] = config.embedding.api_base

    kwargs["model"] = config.embedding.model

    return resolve_variable(config.embedding.use)(**kwargs)


def get_qdrant_client() -> QdrantClient:
    """Get the Qdrant client based on configuration."""
    config = get_knowledge_base_config()

    if config.qdrant.mode == "server":
        if not config.qdrant.url:
            raise ValueError("Qdrant URL is required for server mode")
        return QdrantClient(url=config.qdrant.url, api_key=config.qdrant.api_key)
    return QdrantClient(path=config.qdrant.local_path)


class KnowledgeBaseRetriever:
    """Retriever for the knowledge base."""

    def __init__(self):
        """Initialize the retriever."""
        self.config = get_knowledge_base_config()
        self.client = get_qdrant_client()
        self.embeddings = get_embedding_model()

    def _search_collection(
        self,
        collection_name: str,
        query: str,
        doc_ids: list[str] | None = None,
    ) -> list[dict]:
        vector_store = QdrantVectorStore(
            client=self.client,
            collection_name=collection_name,
            embedding=self.embeddings,
        )

        qdrant_filter = None
        if doc_ids:
            qdrant_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="metadata.doc_id",
                        match=models.MatchAny(any=doc_ids),
                    )
                ]
            )

        results = vector_store.similarity_search_with_score(
            query,
            k=self.config.retrieval.top_k,
            filter=qdrant_filter,
            score_threshold=self.config.retrieval.score_threshold,
        )

        formatted_results: list[dict] = []
        for doc, score in results:
            formatted_results.append(
                {
                    "content": doc.page_content,
                    "metadata": doc.metadata,
                    "score": score,
                    "source": doc.metadata.get("source", "Unknown"),
                    "filename": doc.metadata.get(
                        "filename",
                        doc.metadata.get("source", "").split("/")[-1],
                    ),
                    "page": doc.metadata.get("page"),
                    "source_type": doc.metadata.get("source_type", "unknown"),
                    "collection_name": collection_name,
                }
            )

        return formatted_results

    def search(
        self,
        query: str,
        thread_id: str | None = None,
        doc_ids: list[str] | None = None,
    ) -> list[dict]:
        """Search for relevant documents."""
        collections = [self.config.qdrant.collection_name]
        if thread_id:
            collections.insert(
                0,
                get_thread_collection_name(
                    self.config.qdrant.collection_name,
                    thread_id,
                ),
            )

        merged_results: list[dict] = []
        for collection_name in collections:
            try:
                merged_results.extend(
                    self._search_collection(collection_name, query, doc_ids=doc_ids)
                )
            except Exception:
                continue

        try:
            merged_results.extend(
                lexical_search_documents(
                    query,
                    thread_id=thread_id,
                    doc_ids=doc_ids,
                    top_k=self.config.retrieval.top_k,
                )
            )
        except Exception:
            pass

        merged_results.sort(key=lambda item: item.get("score", 0), reverse=True)

        deduped_results: list[dict] = []
        seen_keys: set[tuple[str, int | None, int | None, str]] = set()
        for result in merged_results:
            metadata = result.get("metadata", {})
            dedupe_key = (
                result.get("filename", ""),
                metadata.get("pdf_page_no")
                or metadata.get("page_no")
                or metadata.get("page")
                or metadata.get("line_start"),
                metadata.get("paragraph_no_in_doc")
                or metadata.get("paragraph_no")
                or metadata.get("line_end"),
                result.get("content", ""),
            )
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            deduped_results.append(result)
            if len(deduped_results) >= self.config.retrieval.top_k:
                break

        return deduped_results


def get_retriever() -> KnowledgeBaseRetriever:
    """Get the singleton retriever instance."""
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = KnowledgeBaseRetriever()
    return _retriever_instance
