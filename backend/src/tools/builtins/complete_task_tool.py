"""Structured task-completion signal for subagents that have reached their tool-call budget.

When `SubagentToolLimitMiddleware` detects that a subagent has consumed its
full tool-call budget it forces the model to call this tool.  The tool:

1. Formats the structured arguments into the canonical four-section markdown
   that ``_parse_structured_subtask_result`` understands.
2. Appends a ``ToolMessage`` with that formatted text to the conversation.
3. Routes the graph to ``END`` so the subagent terminates immediately without
   one more model round-trip.

The executor then picks up the ``ToolMessage`` (by name ``complete_task``) and
uses it as ``result.result``, identical to the result of a naturally-completed
task.
"""

from __future__ import annotations

from typing import Annotated

from langchain.tools import InjectedToolCallId, tool
from langchain_core.messages import ToolMessage
from langgraph.constants import END
from langgraph.types import Command


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _fmt_list(items: list[str] | None, fallback: str = "- 无") -> str:
    """Render a bullet list, falling back to *fallback* when empty."""
    cleaned = [f"- {item.strip()}" for item in (items or []) if item and item.strip()]
    return "\n".join(cleaned) if cleaned else fallback


def format_completion_result(
    summary: str,
    findings: list[str] | None,
    citations: list[str] | None,
    open_questions: list[str] | None,
) -> str:
    """Format structured completion args into the canonical markdown sections."""
    parts: list[str] = [
        f"## 任务结果\n{summary.strip() or '（无）'}",
        f"## 关键发现\n{_fmt_list(findings)}",
        f"## 关键引文\n{_fmt_list(citations)}",
        f"## 未解决缺口\n{_fmt_list(open_questions)}",
    ]
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

@tool("complete_task", parse_docstring=True)
def complete_task_tool(
    summary: str,
    findings: list[str],
    citations: list[str],
    open_questions: list[str],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Signal task completion with a structured result summary.

    Call this tool when you have finished your work *or* when you are instructed
    by the system to stop and summarise because the tool-call budget is
    exhausted.  Do **not** call any other tool after this one.

    Args:
        summary: Summary of what was found and, if retrieval was inconclusive,
            why it was not sufficient.
        findings: List of confirmed facts.  Pass an empty list if none were
            found.
        citations: Citation references from the retrieved material.  Pass an
            empty list if none are available.
        open_questions: Recommendations for the lead agent: should it retry with
            a narrower scope, pivot to a different direction, or abandon this
            search path entirely?  Pass an empty list if no follow-up is needed.
    """
    formatted = format_completion_result(summary, findings, citations, open_questions)
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=formatted,
                    tool_call_id=tool_call_id,
                    name="complete_task",
                )
            ]
        },
        goto=END,
    )
