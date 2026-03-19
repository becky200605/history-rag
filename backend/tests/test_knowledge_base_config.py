"""Tests for knowledge base configuration, including MinerU settings."""

from src.config.knowledge_base_config import (
    KnowledgeBaseConfig,
    MineruConfig,
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
