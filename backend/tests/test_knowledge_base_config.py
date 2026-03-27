"""Tests for knowledge base configuration, including MinerU settings."""

from src.config.knowledge_base_config import (
    BookMetadataConfig,
    KnowledgeBaseConfig,
    MineruConfig,
    TranslationRpcConfig,
    load_knowledge_base_config_from_dict,
    get_knowledge_base_config,
)


class TestMineruConfig:
    """Tests for MineruConfig defaults and integration with KnowledgeBaseConfig."""

    def test_mineru_default_disabled(self):
        """MineruConfig should be disabled by default when not provided."""
        cfg = KnowledgeBaseConfig()
        assert cfg.mineru is None

    def test_mineru_custom_config(self):
        """Custom Mineru configuration should be loaded correctly."""
        data = {
            "enabled": True,
            "docs_path": "knowledge/docs",
            "mineru": {
                "enabled": True,
                "target": "mineru.internal:50051",
                "use_tls": True,
                "api_token": "test-token",
                "model_version": "vlm-test",
                "request_timeout": 10,
            },
        }

        load_knowledge_base_config_from_dict(data)
        cfg = get_knowledge_base_config()

        assert cfg.enabled is True
        assert isinstance(cfg.mineru, MineruConfig)
        assert cfg.mineru.enabled is True
        assert cfg.mineru.target == "mineru.internal:50051"
        assert cfg.mineru.use_tls is True
        assert cfg.mineru.api_token == "test-token"
        assert cfg.mineru.model_version == "vlm-test"
        assert cfg.mineru.request_timeout == 10

    def test_book_metadata_custom_config(self):
        data = {
            "enabled": True,
            "docs_path": "knowledge/docs",
            "book_metadata": {
                "enabled": True,
                "model_name": "doubao-seed-2.0-pro",
                "front_page_limit": 12,
                "body_sample_count": 4,
                "max_excerpt_chars": 1600,
            },
        }

        load_knowledge_base_config_from_dict(data)
        cfg = get_knowledge_base_config()

        assert isinstance(cfg.book_metadata, BookMetadataConfig)
        assert cfg.book_metadata.enabled is True
        assert cfg.book_metadata.model_name == "doubao-seed-2.0-pro"
        assert cfg.book_metadata.front_page_limit == 12
        assert cfg.book_metadata.body_sample_count == 4
        assert cfg.book_metadata.max_excerpt_chars == 1600

    def test_translation_rpc_custom_config(self):
        data = {
            "enabled": True,
            "docs_path": "knowledge/docs",
            "translation_rpc": {
                "enabled": True,
                "target": "translation.internal:50052",
                "use_tls": True,
                "api_token": "translation-token",
                "request_timeout": 25,
            },
        }

        load_knowledge_base_config_from_dict(data)
        cfg = get_knowledge_base_config()

        assert isinstance(cfg.translation_rpc, TranslationRpcConfig)
        assert cfg.translation_rpc.enabled is True
        assert cfg.translation_rpc.target == "translation.internal:50052"
        assert cfg.translation_rpc.use_tls is True
        assert cfg.translation_rpc.api_token == "translation-token"
        assert cfg.translation_rpc.request_timeout == 25
