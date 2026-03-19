from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class QdrantConfig(BaseModel):
    """Configuration for Qdrant vector database."""

    mode: Literal["local", "server"] = Field(
        default="local",
        description="Qdrant mode: 'local' (embedded) or 'server' (client-server).",
    )
    local_path: str = Field(
        default=".deer-flow/qdrant",
        description="Path for local Qdrant storage (only used when mode='local').",
    )
    url: str | None = Field(
        default=None,
        description="Qdrant server URL (only used when mode='server').",
    )
    api_key: str | None = Field(
        default=None,
        description="Qdrant API key (only used when mode='server').",
    )
    collection_name: str = Field(
        default="knowledge_base",
        description="Name of the Qdrant collection.",
    )


class EmbeddingConfig(BaseModel):
    """Configuration for embedding model."""

    use: str = Field(
        description="LangChain embedding class path (e.g. 'langchain_openai:OpenAIEmbeddings').",
    )
    model: str = Field(
        description="Model name/id to use.",
    )
    api_key: str | None = Field(
        default=None,
        description="API key for the embedding service.",
    )
    api_base: str | None = Field(
        default=None,
        description="API base URL for the embedding service (optional).",
    )


class ChunkingConfig(BaseModel):
    """Configuration for text chunking."""

    chunk_size: int = Field(
        default=1000,
        description="Size of text chunks in characters.",
    )
    chunk_overlap: int = Field(
        default=200,
        description="Overlap between chunks in characters.",
    )


class RetrievalConfig(BaseModel):
    """Configuration for retrieval parameters."""

    top_k: int = Field(
        default=5,
        description="Number of relevant chunks to retrieve.",
    )
    score_threshold: float = Field(
        default=0.3,
        description="Minimum similarity score threshold (0.0 to 1.0).",
    )


class MineruConfig(BaseModel):
    """Configuration for MinerU HTTP API based PDF conversion."""

    enabled: bool = Field(
        default=False,
        description="Whether MinerU-based PDF → Markdown conversion is enabled.",
    )
    base_url: str = Field(
        default="https://mineru.net",
        description="Base URL for the MinerU API (e.g. https://mineru.net).",
    )
    api_path: str = Field(
        default="/api/v4/extract/task",
        description="MinerU extract task API path.",
    )
    api_token: str | None = Field(
        default=None,
        description="API token for the MinerU service.",
    )
    model_version: str = Field(
        default="vlm",
        description="Model version to use when calling MinerU (e.g. 'vlm').",
    )
    request_timeout: int = Field(
        default=60,
        description="Timeout in seconds for the HTTP request to MinerU.",
    )


class KnowledgeBaseConfig(BaseModel):
    """Configuration for the Knowledge Base RAG system."""

    enabled: bool = Field(
        default=False,
        description="Whether the knowledge base system is enabled.",
    )
    docs_path: str = Field(
        default="knowledge/docs",
        description="Path to the directory containing knowledge documents.",
    )
    qdrant: QdrantConfig = Field(
        default_factory=QdrantConfig,
        description="Qdrant vector database configuration.",
    )
    embedding: EmbeddingConfig | None = Field(
        default=None,
        description="Embedding model configuration.",
    )
    chunking: ChunkingConfig = Field(
        default_factory=ChunkingConfig,
        description="Text chunking configuration.",
    )
    retrieval: RetrievalConfig = Field(
        default_factory=RetrievalConfig,
        description="Retrieval parameters.",
    )
    mineru: MineruConfig | None = Field(
        default=None,
        description="Optional MinerU KIE configuration for PDF → Markdown conversion.",
    )

    model_config = ConfigDict(extra="allow")


_knowledge_base_config: KnowledgeBaseConfig | None = None


def load_knowledge_base_config_from_dict(config_dict: dict[str, Any]) -> None:
    """Load knowledge base config from a dictionary.

    Args:
        config_dict: Dictionary containing knowledge base configuration.
    """
    global _knowledge_base_config
    if config_dict:
        _knowledge_base_config = KnowledgeBaseConfig(**config_dict)
    else:
        _knowledge_base_config = KnowledgeBaseConfig(enabled=False)


def get_knowledge_base_config() -> KnowledgeBaseConfig:
    """Get the global knowledge base configuration.

    Returns:
        The knowledge base configuration object.
    """
    global _knowledge_base_config
    if _knowledge_base_config is None:
        # Return default disabled config if not loaded
        return KnowledgeBaseConfig(enabled=False)
    return _knowledge_base_config
