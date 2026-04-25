"""Todo middleware that can dispatch in-progress todo batches to subagents."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import replace
from typing import Annotated, Any, Literal

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.todo import WRITE_TODOS_SYSTEM_PROMPT, WRITE_TODOS_TOOL_DESCRIPTION
from langchain.tools import InjectedToolCallId, ToolRuntime
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from langgraph.runtime import Runtime
from langgraph.types import Command
from langgraph.typing import ContextT
from typing_extensions import NotRequired, TypedDict, cast, override

from src.agents.lead_agent.prompt import get_skills_prompt_section
from src.agents.thread_state import ThreadState
from src.subagents import SubagentExecutor, get_subagent_config
from src.subagents.executor import SubagentStatus, get_background_task_result
from src.utils.error_logging import append_error_doc
from src.utils.subtask_logging import log_subtask_event

logger = logging.getLogger(__name__)


class Todo(TypedDict):
    """Todo item shown to the user and optionally bound to a subagent task."""

    content: str
    status: Literal["pending", "in_progress", "completed", "failed"]
    id: NotRequired[str]
    task_id: NotRequired[str]
    task_prompt: NotRequired[str]
    subagent_type: NotRequired[Literal["general-purpose", "bash"]]
    result_summary: NotRequired[str]
    error: NotRequired[str]


class ParallelDispatchState(TypedDict):
    """State recorded when a parallel todo batch is dispatched."""

    dispatched: bool
    todo_ids: list[str]
    task_ids: list[str]


class PlanningState(ThreadState):
    """Agent state carrying todo-board data."""

    todos: NotRequired[list[Todo] | None]


def _clip_text(text: str, *, limit: int = 240) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _build_default_task_prompt(todo: Todo) -> str:
    return (
        "你只负责执行下面这一项 todo，不要扩展到其他任务，不要替主代理写最终总答案。\n\n"
        f"Todo: {todo['content']}\n\n"
        "要求：\n"
        "1. 只围绕这一项任务检索、分析或执行；\n"
        "2. 若属于历史 / 财政史问题，优先使用本地知识库工具并保留关键引文；\n"
        "3. 返回简明结果：结论、关键证据/引文、未解决缺口；\n"
        "4. 不要接管其他 todo。"
    )


def _serialize_todos_for_event(todos: list[Todo]) -> list[dict[str, Any]]:
    return [dict(todo) for todo in todos]


def _should_preserve_bound_task_status(
    *,
    raw: Todo,
    existing_todo: Todo | None,
    next_status: Literal["pending", "in_progress", "completed", "failed"],
) -> bool:
    if existing_todo is None:
        return False

    if not existing_todo.get("task_id") or raw.get("task_id"):
        return False

    existing_status = cast(
        Literal["pending", "in_progress", "completed", "failed"],
        existing_todo.get("status", "pending"),
    )

    # Once a todo is bound to a real subtask, the lead model should not mutate
    # that task's lifecycle without providing a new task binding. The executor
    # owns the transition from running -> completed/failed.
    if existing_status == "in_progress" and next_status != "in_progress":
        return True

    # Also prevent later board rewrites from regressing an executor-owned final state.
    if existing_status in {"completed", "failed"} and next_status != existing_status:
        return True

    return False


class TodoListMiddleware(AgentMiddleware[PlanningState]):
    """Middleware that turns the todo list into a lightweight execution board."""

    state_schema = PlanningState

    def __init__(
        self,
        *,
        system_prompt: str = WRITE_TODOS_SYSTEM_PROMPT,
        tool_description: str = WRITE_TODOS_TOOL_DESCRIPTION,
        subagent_enabled: bool = False,
        max_concurrent_subagents: int = 3,
    ) -> None:
        super().__init__()
        self.system_prompt = system_prompt
        self.tool_description = tool_description
        self.subagent_enabled = subagent_enabled
        self.max_concurrent_subagents = max_concurrent_subagents

        @tool(description=self.tool_description)
        def write_todos(
            runtime: ToolRuntime[ContextT, ThreadState],
            todos: list[Todo],
            tool_call_id: Annotated[str, InjectedToolCallId],
        ) -> Command:
            return self._handle_write_todos(
                runtime=runtime,
                todos=todos,
                tool_call_id=tool_call_id,
            )

        self.tools = [write_todos]

    def _normalize_todos(self, incoming: list[Todo], existing: list[Todo] | None) -> list[Todo]:
        existing = existing or []
        by_id = {todo.get("id"): todo for todo in existing if todo.get("id")}
        by_content = {todo.get("content"): todo for todo in existing if todo.get("content")}
        normalized: list[Todo] = []

        for raw in incoming:
            content = str(raw.get("content", "")).strip()
            if not content:
                continue

            existing_todo = None
            if raw.get("id") and raw.get("id") in by_id:
                existing_todo = by_id[raw["id"]]
            elif content in by_content:
                existing_todo = by_content[content]

            status = cast(
                Literal["pending", "in_progress", "completed", "failed"],
                raw.get("status", existing_todo.get("status") if existing_todo else "pending"),
            )
            if status not in {"pending", "in_progress", "completed", "failed"}:
                status = "pending"

            if _should_preserve_bound_task_status(
                raw=raw,
                existing_todo=existing_todo,
                next_status=status,
            ):
                status = cast(
                    Literal["pending", "in_progress", "completed", "failed"],
                    existing_todo.get("status", status),
                )

            todo_id = str(raw.get("id") or (existing_todo.get("id") if existing_todo else "") or f"todo-{uuid.uuid4().hex[:8]}")
            todo: Todo = {
                "id": todo_id,
                "content": content,
                "status": status,
            }

            for field in ("task_id", "task_prompt", "subagent_type", "result_summary", "error"):
                value = raw.get(field)
                if value in (None, "") and existing_todo is not None:
                    value = existing_todo.get(field)
                if value not in (None, ""):
                    todo[field] = cast(Any, value)

            if (
                status in {"pending", "in_progress"}
                and "task_id" not in raw
                and existing_todo is not None
                and raw.get("status") != existing_todo.get("status")
            ):
                todo.pop("task_id", None)
                todo.pop("result_summary", None)
                todo.pop("error", None)

            normalized.append(todo)

        return normalized

    def _build_subagent_config(self, subagent_type: str):
        config = get_subagent_config(subagent_type)
        if config is None:
            return None

        overrides: dict[str, Any] = {}
        skills_section = get_skills_prompt_section()
        if skills_section:
            overrides["system_prompt"] = config.system_prompt + "\n\n" + skills_section

        if overrides:
            config = replace(config, **overrides)
        return config

    def _dispatch_parallel_todos(
        self,
        *,
        runtime: Any,
        todos: list[Todo],
        tool_call_id: str,
    ) -> tuple[list[Todo], list[str], ParallelDispatchState]:
        dispatch_state: ParallelDispatchState = {
            "dispatched": False,
            "todo_ids": [],
            "task_ids": [],
        }
        log_subtask_event(
            "write_todos_received",
            tool_call_id=tool_call_id,
            todo_count=len(todos),
            in_progress_or_pending_count=sum(1 for todo in todos if todo["status"] in {"in_progress", "pending"}),
            subagent_enabled=self.subagent_enabled,
            max_concurrent_subagents=self.max_concurrent_subagents,
        )
        if not self.subagent_enabled:
            log_subtask_event(
                "write_todos_dispatch_skipped",
                tool_call_id=tool_call_id,
                reason="subagent_disabled",
                todos=todos,
            )
            return todos, [], dispatch_state

        queued_todos = [
            todo for todo in todos if todo["status"] in {"in_progress", "pending"} and not todo.get("task_id")
        ]
        if not queued_todos:
            log_subtask_event(
                "write_todos_dispatch_skipped",
                tool_call_id=tool_call_id,
                reason="no_queued_todos",
                todos=todos,
            )
            return todos, [], dispatch_state

        writer = get_stream_writer()
        trace_id = None
        sandbox_state = None
        thread_data = None
        thread_id = None
        parent_model = None

        if runtime is not None:
            sandbox_state = runtime.state.get("sandbox")
            thread_data = runtime.state.get("thread_data")
            thread_id = runtime.context.get("thread_id")
            metadata = runtime.config.get("metadata", {})
            parent_model = metadata.get("model_name")
            trace_id = metadata.get("trace_id")

        trace_id = trace_id or str(uuid.uuid4())[:8]

        # Lazy import to avoid circular dependency during app startup.
        from src.tools import get_available_tools

        tools = get_available_tools(model_name=parent_model, subagent_enabled=False)

        summary_lines: list[str] = []
        if len(queued_todos) > self.max_concurrent_subagents:
            summary_lines.append(
                f"检测到 {len(queued_todos)} 个待执行 todo；系统会按最多 {self.max_concurrent_subagents} 个并发子任务自动分批执行。"
            )
        writer({"type": "todo_board_updated", "todos": _serialize_todos_for_event(todos)})

        queue: list[Todo] = list(queued_todos)
        launched: dict[str, dict[str, Any]] = {}

        while queue or launched:
            while queue and len(launched) < self.max_concurrent_subagents:
                todo = queue.pop(0)
                subagent_type = cast(str, todo.get("subagent_type") or "general-purpose")
                config = self._build_subagent_config(subagent_type)
                if config is None:
                    todo["status"] = "failed"
                    todo["error"] = f"Unknown subagent type: {subagent_type}"
                    append_error_doc(
                        location="parallel_todo_list_middleware",
                        summary="Todo could not be dispatched because subagent type was unknown",
                        error=todo["error"],
                        context={
                            "todo_id": todo.get("id"),
                            "content": todo["content"],
                            "subagent_type": subagent_type,
                        },
                    )
                    writer({"type": "todo_board_updated", "todos": _serialize_todos_for_event(todos)})
                    summary_lines.append(f"[failed] {todo['content']}：未知子代理类型 {subagent_type}")
                    continue

                executor = SubagentExecutor(
                    config=config,
                    tools=tools,
                    parent_model=parent_model,
                    sandbox_state=sandbox_state,
                    thread_data=thread_data,
                    thread_id=thread_id,
                    trace_id=trace_id,
                )

                task_id = f"{tool_call_id}:{todo['id']}"
                task_prompt = cast(str, todo.get("task_prompt") or _build_default_task_prompt(todo))
                todo["status"] = "in_progress"
                todo["task_id"] = task_id
                todo["subagent_type"] = cast(Any, subagent_type)
                todo["task_prompt"] = task_prompt
                dispatch_state["dispatched"] = True
                dispatch_state["todo_ids"].append(cast(str, todo["id"]))
                dispatch_state["task_ids"].append(task_id)
                writer({"type": "task_started", "task_id": task_id, "description": _clip_text(todo["content"], limit=60)})
                writer({"type": "todo_board_updated", "todos": _serialize_todos_for_event(todos)})
                launched[task_id] = {
                    "todo": todo,
                    "message_count": 0,
                    "timeout_seconds": config.timeout_seconds,
                }
                log_subtask_event(
                    "subtask_dispatching",
                    tool_call_id=tool_call_id,
                    task_id=task_id,
                    todo_id=todo.get("id"),
                    content=todo["content"],
                    subagent_type=subagent_type,
                    queue_remaining=len(queue),
                    launched=len(launched),
                    timeout_seconds=config.timeout_seconds,
                )
                executor.execute_async(task_prompt, task_id=task_id)
                logger.info(
                    "[trace=%s] Dispatched todo subtask %s (active=%s queued=%s): %s",
                    trace_id,
                    task_id,
                    len(launched),
                    len(queue),
                    todo["content"],
                )

            if not launched:
                break

            completed_task_ids: list[str] = []
            for task_id, meta in list(launched.items()):
                result = get_background_task_result(task_id)
                todo = cast(Todo, meta["todo"])

                if result is None:
                    todo["status"] = "failed"
                    todo["error"] = "Task disappeared from background tasks"
                    log_subtask_event(
                        "subtask_missing",
                        task_id=task_id,
                        todo_id=todo.get("id"),
                        content=todo["content"],
                    )
                    append_error_doc(
                        location="parallel_todo_list_middleware",
                        summary="Todo-linked subtask disappeared before completion",
                        error=todo["error"],
                        context={
                            "task_id": task_id,
                            "todo_id": todo.get("id"),
                            "content": todo["content"],
                        },
                    )
                    writer({"type": "task_failed", "task_id": task_id, "error": todo["error"]})
                    writer({"type": "todo_board_updated", "todos": _serialize_todos_for_event(todos)})
                    summary_lines.append(f"[failed] {todo['content']}：{todo['error']}")
                    completed_task_ids.append(task_id)
                    continue

                current_message_count = len(result.ai_messages)
                if current_message_count > meta["message_count"]:
                    for i in range(meta["message_count"], current_message_count):
                        writer(
                            {
                                "type": "task_running",
                                "task_id": task_id,
                                "message": result.ai_messages[i],
                                "message_index": i + 1,
                                "total_messages": current_message_count,
                            }
                        )
                    meta["message_count"] = current_message_count

                if result.status == SubagentStatus.COMPLETED:
                    todo["status"] = "completed"
                    if result.result:
                        todo["result_summary"] = _clip_text(result.result, limit=320)
                    todo.pop("error", None)
                    log_subtask_event(
                        "subtask_completed",
                        task_id=task_id,
                        todo_id=todo.get("id"),
                        content=todo["content"],
                        result_summary=todo.get("result_summary"),
                    )
                    writer({"type": "task_completed", "task_id": task_id, "result": result.result})
                    writer({"type": "todo_board_updated", "todos": _serialize_todos_for_event(todos)})
                    summary_lines.append(f"[completed] {todo['content']}：{todo.get('result_summary', '已完成')}")
                    completed_task_ids.append(task_id)
                elif result.status == SubagentStatus.FAILED:
                    todo["status"] = "failed"
                    todo["error"] = result.error or "Unknown subtask error"
                    log_subtask_event(
                        "subtask_failed",
                        task_id=task_id,
                        todo_id=todo.get("id"),
                        content=todo["content"],
                        error=todo["error"],
                    )
                    append_error_doc(
                        location="parallel_todo_list_middleware",
                        summary="Todo-linked subtask failed",
                        error=todo["error"],
                        context={
                            "task_id": task_id,
                            "todo_id": todo.get("id"),
                            "content": todo["content"],
                        },
                    )
                    writer({"type": "task_failed", "task_id": task_id, "error": todo["error"]})
                    writer({"type": "todo_board_updated", "todos": _serialize_todos_for_event(todos)})
                    summary_lines.append(f"[failed] {todo['content']}：{todo['error']}")
                    completed_task_ids.append(task_id)
                elif result.status == SubagentStatus.TIMED_OUT:
                    todo["status"] = "failed"
                    todo["error"] = result.error or "Subtask timed out"
                    log_subtask_event(
                        "subtask_timed_out",
                        task_id=task_id,
                        todo_id=todo.get("id"),
                        content=todo["content"],
                        error=todo["error"],
                    )
                    append_error_doc(
                        location="parallel_todo_list_middleware",
                        summary="Todo-linked subtask timed out",
                        error=todo["error"],
                        context={
                            "task_id": task_id,
                            "todo_id": todo.get("id"),
                            "content": todo["content"],
                        },
                    )
                    writer({"type": "task_timed_out", "task_id": task_id, "error": todo["error"]})
                    writer({"type": "todo_board_updated", "todos": _serialize_todos_for_event(todos)})
                    summary_lines.append(f"[failed] {todo['content']}：{todo['error']}")
                    completed_task_ids.append(task_id)

            for task_id in completed_task_ids:
                launched.pop(task_id, None)

            if launched or queue:
                time.sleep(0.25)

        return todos, summary_lines, dispatch_state

    def _build_todo_orchestration_state(
        self,
        *,
        tool_call_id: str,
        dispatch_state: ParallelDispatchState,
    ) -> dict[str, Any] | None:
        return None

    def _build_tool_message(self, todos: list[Todo], summary_lines: list[str]) -> str:
        lines = ["Updated todo board."]
        if summary_lines:
            lines.append("Parallel dispatch summary:")
            lines.extend(f"- {line}" for line in summary_lines)
        else:
            lines.append("No subagent batch was dispatched.")

        lines.append("Current todos:")
        for todo in todos:
            status = todo.get("status", "pending")
            content = todo.get("content", "")
            line = f"- [{status}] {content}"
            if todo.get("result_summary"):
                line += f" | result: {todo['result_summary']}"
            if todo.get("error"):
                line += f" | error: {todo['error']}"
            lines.append(line)

        return "\n".join(lines)

    def _handle_write_todos(self, *, runtime: Any, todos: list[Todo], tool_call_id: str) -> Command:
        existing_todos = cast(list[Todo] | None, runtime.state.get("todos") if runtime is not None else None)
        normalized = self._normalize_todos(todos, existing_todos)
        normalized, summary_lines, dispatch_state = self._dispatch_parallel_todos(
            runtime=runtime,
            todos=normalized,
            tool_call_id=tool_call_id,
        )
        return Command(
            update={
                "todos": normalized,
                "todo_orchestration": self._build_todo_orchestration_state(
                    tool_call_id=tool_call_id,
                    dispatch_state=dispatch_state,
                ),
                "messages": [ToolMessage(self._build_tool_message(normalized, summary_lines), tool_call_id=tool_call_id)],
            },
        )

    @override
    def wrap_model_call(self, request, handler):
        if request.system_message is not None:
            new_system_content = [
                *request.system_message.content_blocks,
                {"type": "text", "text": f"\n\n{self.system_prompt}"},
            ]
        else:
            new_system_content = [{"type": "text", "text": self.system_prompt}]
        new_system_message = SystemMessage(content=cast("list[str | dict[str, str]]", new_system_content))
        return handler(request.override(system_message=new_system_message))

    @override
    async def awrap_model_call(self, request, handler):
        if request.system_message is not None:
            new_system_content = [
                *request.system_message.content_blocks,
                {"type": "text", "text": f"\n\n{self.system_prompt}"},
            ]
        else:
            new_system_content = [{"type": "text", "text": self.system_prompt}]
        new_system_message = SystemMessage(content=cast("list[str | dict[str, str]]", new_system_content))
        return await handler(request.override(system_message=new_system_message))

    def _last_ai_message(self, state: PlanningState) -> AIMessage | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        return next((msg for msg in reversed(messages) if isinstance(msg, AIMessage)), None)

    def _single_write_todos_only(self, state: PlanningState) -> dict[str, Any] | None:
        last_ai_msg = self._last_ai_message(state)
        if not last_ai_msg or not last_ai_msg.tool_calls:
            return None

        write_todos_calls = [tc for tc in last_ai_msg.tool_calls if tc["name"] == "write_todos"]
        if len(write_todos_calls) <= 1:
            return None

        error_messages = [
            ToolMessage(
                content=(
                    "Error: `write_todos` replaces the entire todo board, so it cannot be "
                    "called multiple times in parallel. Please call it only once per model turn."
                ),
                tool_call_id=tc["id"],
                status="error",
            )
            for tc in write_todos_calls
        ]
        return {"messages": error_messages}

    def _write_todos_is_phase_boundary(self, state: PlanningState) -> dict[str, Any] | None:
        last_ai_msg = self._last_ai_message(state)
        if not last_ai_msg or not last_ai_msg.tool_calls:
            return None

        write_todos_calls = [tc for tc in last_ai_msg.tool_calls if tc["name"] == "write_todos"]
        if not write_todos_calls:
            return None

        non_write_todos_calls = [tc for tc in last_ai_msg.tool_calls if tc["name"] != "write_todos"]
        if not non_write_todos_calls:
            return None

        error_messages = [
            ToolMessage(
                content=(
                    "Error: `write_todos` is a phase boundary for parallel orchestration. "
                    "Do not pair it with other tool calls in the same response. "
                    "Submit only `write_todos`, wait for the todo board update, then continue."
                ),
                tool_call_id=tc["id"],
                status="error",
            )
            for tc in non_write_todos_calls
        ]
        return {"messages": error_messages}

    @override
    def after_model(self, state: PlanningState, runtime: Runtime[ContextT]) -> dict[str, Any] | None:
        return (
            self._single_write_todos_only(state)
            or self._write_todos_is_phase_boundary(state)
        )

    @override
    async def aafter_model(self, state: PlanningState, runtime: Runtime[ContextT]) -> dict[str, Any] | None:
        return (
            self._single_write_todos_only(state)
            or self._write_todos_is_phase_boundary(state)
        )
