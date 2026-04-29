from __future__ import annotations

import re
from typing import Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from src.agents.middlewares.title_middleware import generate_title_candidate
from src.community.knowledge_base.task_memory import (
    build_task_memory_injection_message,
    search_task_memory,
    upsert_task_memory_record,
)


class TaskMemoryMiddlewareState(AgentState):
    current_task_title: NotRequired[str | None]
    current_task_human_index: NotRequired[int | None]
    task_memory_injected_human_index: NotRequired[int | None]
    task_memory_saved_human_index: NotRequired[int | None]
    title: NotRequired[str | None]


def _stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content or "")


def _strip_injected_context(text: str) -> str:
    stripped = re.sub(r"<uploaded_files>[\s\S]*?</uploaded_files>", "", text)
    return stripped.strip()


def _extract_citations(text: str) -> list[str]:
    seen: set[str] = set()
    citations: list[str] = []
    for citation in re.findall(r"\[citation:[^\]]+\]\((?:<[^>\n]+>|[^)\n]+)\)", text):
        if citation in seen:
            continue
        seen.add(citation)
        citations.append(citation)
    return citations


def _latest_human_message(messages: list[Any]) -> tuple[int, HumanMessage] | None:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, HumanMessage):
            content = _stringify_content(message.content)
            if "<task_memory_matches>" in content:
                continue
            return index, message
    return None


class TaskMemoryMiddleware(AgentMiddleware[TaskMemoryMiddlewareState]):
    """Generate a task title, inject historical matches, and persist completed main-task results."""

    state_schema = TaskMemoryMiddlewareState

    @override
    def before_model(self, state: TaskMemoryMiddlewareState, runtime: Runtime) -> dict | None:
        messages = list(state.get("messages", []))
        latest_human = _latest_human_message(messages)
        if latest_human is None:
            return None

        human_index, human_message = latest_human
        query = _strip_injected_context(_stringify_content(human_message.content))
        if not query:
            return None

        updates: dict[str, Any] = {}
        current_task_title = str(state.get("current_task_title") or "").strip()
        if state.get("current_task_human_index") != human_index or not current_task_title:
            current_task_title = generate_title_candidate(query)
            updates["current_task_title"] = current_task_title
            updates["current_task_human_index"] = human_index
            if not state.get("title"):
                updates["title"] = current_task_title

        if state.get("task_memory_injected_human_index") == human_index:
            return updates or None

        try:
            matches = search_task_memory(query, title=current_task_title, top_k=3)
        except Exception:
            matches = []
        updates["task_memory_injected_human_index"] = human_index
        if not matches:
            return updates or None

        updates["messages"] = [
            HumanMessage(
                content=build_task_memory_injection_message(
                    title=current_task_title,
                    query=query,
                    results=matches,
                )
            )
        ]
        return updates

    @override
    def after_agent(self, state: TaskMemoryMiddlewareState, runtime: Runtime) -> dict | None:
        current_task_title = str(state.get("current_task_title") or "").strip()
        current_task_human_index = state.get("current_task_human_index")
        if not current_task_title or current_task_human_index is None:
            return None
        if state.get("task_memory_saved_human_index") == current_task_human_index:
            return None

        messages = list(state.get("messages", []))
        if current_task_human_index >= len(messages):
            return None

        human_message = messages[current_task_human_index]
        latest_message = messages[-1] if messages else None
        if not isinstance(human_message, HumanMessage) or not isinstance(latest_message, AIMessage):
            return None
        if getattr(latest_message, "tool_calls", None):
            return None

        query = _strip_injected_context(_stringify_content(human_message.content))
        summary = _stringify_content(latest_message.content).strip()
        if not query or not summary:
            return None

        try:
            upsert_task_memory_record(
                title=current_task_title,
                query=query,
                summary=summary,
                citations=_extract_citations(summary),
                findings=[],
                open_questions=[],
                task_level="main",
                thread_id=runtime.context.get("thread_id"),
                user_id=runtime.context.get("user_id"),
                task_id=f"main:{runtime.context.get('thread_id')}:{current_task_human_index}",
                raw_result=summary,
            )
        except Exception:
            return None
        return {"task_memory_saved_human_index": current_task_human_index}
