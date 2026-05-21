"""Tests for the complete_task built-in tool."""

from __future__ import annotations

import pytest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.tools.builtins.complete_task_tool import complete_task_tool, format_completion_result


# ---------------------------------------------------------------------------
# format_completion_result (pure function, no tool plumbing needed)
# ---------------------------------------------------------------------------


class TestFormatCompletionResult:
    def test_all_sections_present(self):
        text = format_completion_result(
            summary="Found some evidence.",
            findings=["Fact A", "Fact B"],
            citations=["[citation:1]", "[citation:2]"],
            open_questions=["Try a narrower scope."],
        )
        assert "## 任务结果" in text
        assert "Found some evidence." in text
        assert "## 关键发现" in text
        assert "- Fact A" in text
        assert "## 关键引文" in text
        assert "[citation:1]" in text
        assert "## 未解决缺口" in text
        assert "Try a narrower scope." in text

    def test_empty_lists_render_fallback(self):
        text = format_completion_result(
            summary="Nothing found.",
            findings=[],
            citations=[],
            open_questions=[],
        )
        # Each empty section should render "- 无"
        assert text.count("- 无") == 3

    def test_whitespace_stripped(self):
        text = format_completion_result(
            summary="  Summary with spaces.  ",
            findings=["  Padded fact  "],
            citations=[],
            open_questions=[],
        )
        assert "Summary with spaces." in text
        assert "- Padded fact" in text

    def test_blank_items_ignored(self):
        text = format_completion_result(
            summary="s",
            findings=["", "  ", "Valid"],
            citations=[],
            open_questions=[],
        )
        assert "- Valid" in text
        # Blank items must not become empty bullets
        assert "- \n" not in text
        assert "- \n" not in text

    def test_sections_ordered_correctly(self):
        text = format_completion_result("s", ["f"], ["c"], ["q"])
        pos_result = text.index("## 任务结果")
        pos_findings = text.index("## 关键发现")
        pos_citations = text.index("## 关键引文")
        pos_gaps = text.index("## 未解决缺口")
        assert pos_result < pos_findings < pos_citations < pos_gaps


# ---------------------------------------------------------------------------
# complete_task_tool invocation (using .invoke() to bypass runtime injection)
# ---------------------------------------------------------------------------


class TestCompleteTaskTool:
    """Test the tool's Command return value by calling the underlying function directly."""

    def _invoke(self, **kwargs) -> Command:
        """Call the tool's underlying function with a dummy tool_call_id."""
        from src.tools.builtins.complete_task_tool import complete_task_tool as _tool

        # Access the wrapped function directly to bypass InjectedToolCallId resolution
        return _tool.func(tool_call_id="dummy-id", **kwargs)

    def test_returns_command(self):
        result = self._invoke(
            summary="Done.",
            findings=["F1"],
            citations=["[citation:1]"],
            open_questions=["Next step"],
        )
        assert isinstance(result, Command)

    def test_command_contains_tool_message(self):
        result = self._invoke(
            summary="Done.",
            findings=[],
            citations=[],
            open_questions=[],
        )
        messages = result.update.get("messages", [])
        assert len(messages) == 1
        msg = messages[0]
        assert isinstance(msg, ToolMessage)
        assert msg.name == "complete_task"
        assert msg.tool_call_id == "dummy-id"

    def test_command_routes_to_end(self):
        from langgraph.constants import END

        result = self._invoke(
            summary="Done.",
            findings=[],
            citations=[],
            open_questions=[],
        )
        assert result.goto == END

    def test_tool_message_content_is_formatted_markdown(self):
        result = self._invoke(
            summary="Summary text.",
            findings=["Fact 1"],
            citations=["[citation:5]"],
            open_questions=["Retry"],
        )
        content = result.update["messages"][0].content
        assert "## 任务结果" in content
        assert "Summary text." in content
        assert "## 关键发现" in content
        assert "Fact 1" in content
        assert "## 关键引文" in content
        assert "[citation:5]" in content
        assert "## 未解决缺口" in content
        assert "Retry" in content

    def test_empty_summary_renders_placeholder(self):
        result = self._invoke(
            summary="",
            findings=[],
            citations=[],
            open_questions=[],
        )
        content = result.update["messages"][0].content
        assert "（无）" in content
