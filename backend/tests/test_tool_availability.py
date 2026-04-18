from pathlib import Path

from src.config.app_config import AppConfig
from src.config.extensions_config import ExtensionsConfig


def test_repo_config_disables_file_write_tools(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        ExtensionsConfig,
        "from_file",
        classmethod(lambda cls, config_path=None: ExtensionsConfig()),
    )

    config_path = Path(__file__).resolve().parents[2] / "config.yaml"
    config = AppConfig.from_file(str(config_path))

    tool_names = [tool.name for tool in config.tools]

    assert "write_file" not in tool_names
    assert "str_replace" not in tool_names


def test_runtime_tool_registry_excludes_present_files(monkeypatch) -> None:
    tools_module = (
        Path(__file__).resolve().parents[1] / "src" / "tools" / "tools.py"
    ).read_text(encoding="utf-8")

    assert "present_file_tool" not in tools_module
    assert "present_files" not in tools_module
