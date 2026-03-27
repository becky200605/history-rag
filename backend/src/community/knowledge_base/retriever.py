from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client import models

from src.community.knowledge_base.common import get_thread_collection_name
from src.community.knowledge_base.common import get_user_collection_name
from src.community.knowledge_base.lexical_search import lexical_search_documents
from src.config.knowledge_base_config import get_knowledge_base_config
from src.reflection import resolve_variable

"""
Module for retrieving documents from the knowledge base using Qdrant.
"""

_retriever_instance = None
SCOPE_BOOSTS = {
    "user": 1.05,
    "thread": 1.0,
    "global": 0.95,
}
SOURCE_KIND_BOOSTS = {
    "annotation": 1.30,
    "excerpt": 1.20,
    "upload": 1.10,
    "thread_upload": 1.00,
    "global_document": 0.95,
    "translation": 0.85,
}


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

    def _score_result(self, result: dict) -> float:
        metadata = result.get("metadata", {})
        scope = str(metadata.get("scope") or "global")
        source_kind = str(
            metadata.get("source_kind")
            or (
                "thread_upload"
                if scope == "thread"
                else "upload"
                if scope == "user"
                else "global_document"
            )
        )
        base_score = float(result.get("score", 0.0) or 0.0)
        return base_score * SCOPE_BOOSTS.get(scope, 1.0) * SOURCE_KIND_BOOSTS.get(source_kind, 1.0)

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
        user_id: str | None = None,
        doc_ids: list[str] | None = None,
        scopes: list[str] | None = None,
    ) -> list[dict]:
        """Search for relevant documents."""
        enabled_scopes = scopes or ["user", "thread", "global"]
        collections: list[str] = []
        if user_id and "user" in enabled_scopes:
            collections.append(
                get_user_collection_name(
                    self.config.qdrant.collection_name,
                    user_id,
                ),
            )
        if thread_id:
            if "thread" in enabled_scopes:
                collections.append(
                    get_thread_collection_name(
                        self.config.qdrant.collection_name,
                        thread_id,
                    ),
                )
        if "global" in enabled_scopes:
            collections.append(self.config.qdrant.collection_name)

        merged_results: list[dict] = []
        for collection_name in collections:
            try:
                merged_results.extend(
                    self._search_collection(
                        collection_name,
                        query,
                        doc_ids=doc_ids
                        if collection_name == self.config.qdrant.collection_name
                        else None,
                    )
                )
            except Exception:
                continue

        try:
            merged_results.extend(
                lexical_search_documents(
                    query,
                    thread_id=thread_id,
                    user_id=user_id,
                    doc_ids=doc_ids,
                    scopes=enabled_scopes,
                    top_k=self.config.retrieval.top_k,
                )
            )
        except Exception:
            pass

        for result in merged_results:
            result["weighted_score"] = self._score_result(result)

        merged_results.sort(key=lambda item: item.get("weighted_score", item.get("score", 0)), reverse=True)

        deduped_results: list[dict] = []
        seen_keys: set[tuple[str, int | None, int | None, str, str]] = set()
        for result in merged_results:
            metadata = result.get("metadata", {})
            dedupe_key = (
                metadata.get("origin_doc_id")
                or metadata.get("doc_id")
                or result.get("filename", ""),
                metadata.get("pdf_page_no")
                or metadata.get("page_no")
                or metadata.get("page")
                or metadata.get("line_start"),
                metadata.get("paragraph_no_in_doc")
                or metadata.get("paragraph_no")
                or metadata.get("line_end"),
                result.get("content", ""),
                metadata.get("source_kind", ""),
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
