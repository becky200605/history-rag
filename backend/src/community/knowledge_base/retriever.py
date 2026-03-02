from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

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
    else:
        return QdrantClient(path=config.qdrant.local_path)


class KnowledgeBaseRetriever:
    """Retriever for the knowledge base."""

    def __init__(self):
        """Initialize the retriever."""
        self.config = get_knowledge_base_config()
        self.client = get_qdrant_client()
        self.embeddings = get_embedding_model()
        self.vector_store = QdrantVectorStore(
            client=self.client,
            collection_name=self.config.qdrant.collection_name,
            embedding=self.embeddings,
        )

    def search(self, query: str) -> list[dict]:
        """Search for relevant documents.

        Args:
            query: The search query.

        Returns:
            List of relevant document snippets with metadata.
        """
        results = self.vector_store.similarity_search_with_score(
            query,
            k=self.config.retrieval.top_k,
            score_threshold=self.config.retrieval.score_threshold,
        )

        formatted_results = []
        for doc, score in results:
            formatted_results.append(
                {
                    "content": doc.page_content,
                    "metadata": doc.metadata,
                    "score": score,
                    "source": doc.metadata.get("source", "Unknown"),
                    # Assuming filename is available in metadata or needs to be extracted from source path
                    "filename": doc.metadata.get("filename", doc.metadata.get("source", "").split("/")[-1]),
                }
            )

        return formatted_results


def get_retriever() -> KnowledgeBaseRetriever:
    """Get the singleton retriever instance."""
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = KnowledgeBaseRetriever()
    return _retriever_instance
