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


def test_runtime_tool_registry_exposes_knowledge_search() -> None:
    tools_module = (
        Path(__file__).resolve().parents[1] / "src" / "tools" / "tools.py"
    ).read_text(encoding="utf-8")

    assert "TEMPORARILY_DISABLED_TOOL_NAMES = set()" in tools_module
    assert "tool.name not in TEMPORARILY_DISABLED_TOOL_NAMES" in tools_module


def test_subtask_result_format_fully_replaces_summary_with_task_result() -> None:
    general_purpose = (
        Path(__file__).resolve().parents[1] / "src" / "subagents" / "builtins" / "general_purpose.py"
    ).read_text(encoding="utf-8")
    executor_source = (
        Path(__file__).resolve().parents[1] / "src" / "subagents" / "executor.py"
    ).read_text(encoding="utf-8")

    assert "## 任务结果" in general_purpose
    assert "## 摘要" not in general_purpose
    assert '"任务结果": "summary"' in executor_source
    assert '"摘要": "summary"' not in executor_source


def test_subagents_enable_checkpoint_middleware() -> None:
    executor_source = (
        Path(__file__).resolve().parents[1] / "src" / "subagents" / "executor.py"
    ).read_text(encoding="utf-8")

    assert "KnowledgeCheckpointMiddleware" in executor_source
    assert "KnowledgeCheckpointMiddleware(),  # Enforce checkpoint cadence during raw retrieval loops" in executor_source
