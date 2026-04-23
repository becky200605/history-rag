from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage, ToolMessage

import src.tools as tools_module
from src.agents.middlewares import parallel_todo_list_middleware as todo_module
from src.subagents.config import SubagentConfig


def test_write_todos_dispatches_parallel_batch_and_updates_todos(monkeypatch):
    events: list[dict] = []
    launched_prompts: dict[str, str] = {}

    monkeypatch.setattr(todo_module, "get_stream_writer", lambda: lambda event: events.append(event))
    monkeypatch.setattr(todo_module, "get_skills_prompt_section", lambda: "")
    monkeypatch.setattr(tools_module, "get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(
        todo_module,
        "get_subagent_config",
        lambda name: SubagentConfig(
            name=name,
            description="test",
            system_prompt="test",
            timeout_seconds=5,
        ),
    )

    class FakeExecutor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def execute_async(self, prompt: str, task_id: str):
            launched_prompts[task_id] = prompt
            return task_id

    class FakeStatus:
        COMPLETED = "completed"
        FAILED = "failed"
        TIMED_OUT = "timed_out"

    monkeypatch.setattr(todo_module, "SubagentExecutor", FakeExecutor)
    monkeypatch.setattr(todo_module, "SubagentStatus", FakeStatus)
    monkeypatch.setattr(
        todo_module,
        "get_background_task_result",
        lambda task_id: SimpleNamespace(
            status=FakeStatus.COMPLETED,
            result=f"result for {task_id}",
            error=None,
            ai_messages=[],
        ),
    )

    middleware = todo_module.TodoListMiddleware(
        system_prompt="test",
        tool_description="test",
        subagent_enabled=True,
        max_concurrent_subagents=2,
    )
    runtime = SimpleNamespace(
        state={"todos": [], "sandbox": None, "thread_data": None},
        context={"thread_id": "thread-1"},
        config={"metadata": {"model_name": "test-model", "trace_id": "trace-1"}},
    )

    command = middleware.tools[0].func(
        runtime=runtime,
        todos=[
            {"content": "读《甲书》：查税制", "status": "in_progress"},
            {"content": "读《乙书》：查债务", "status": "in_progress"},
            {"content": "读《丙书》：查币制", "status": "in_progress"},
        ],
        tool_call_id="call-1",
    )

    todos = command.update["todos"]
    assert len(launched_prompts) == 2
    assert len(todos) == 3
    assert todos[0]["status"] == "completed"
    assert todos[1]["status"] == "completed"
    assert todos[2]["status"] == "pending"
    assert command.update["todo_orchestration"]["mode"] == "parallel_batch"
    assert command.update["todo_orchestration"]["dispatched_todo_ids"] == [todos[0]["id"], todos[1]["id"]]
    assert todos[0]["task_id"] == "call-1:" + todos[0]["id"]
    assert "result_summary" in todos[0]
    assert any(event["type"] == "task_started" for event in events)
    assert any(event["type"] == "task_completed" for event in events)
    assert "Parallel dispatch summary:" in command.update["messages"][0].content


def test_write_todos_rejects_mixed_tool_batch():
    middleware = todo_module.TodoListMiddleware(
        system_prompt="test",
        tool_description="test",
        subagent_enabled=True,
        max_concurrent_subagents=2,
    )

    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "write_todos", "args": {"todos": []}, "id": "write-1", "type": "tool_call"},
                    {"name": "bash", "args": {"command": "pwd"}, "id": "bash-1", "type": "tool_call"},
                ],
            )
        ]
    }

    result = middleware.after_model(state, SimpleNamespace())

    assert result is not None
    messages = result["messages"]
    assert len(messages) == 1
    assert isinstance(messages[0], ToolMessage)
    assert messages[0].tool_call_id == "bash-1"
    assert messages[0].status == "error"
    assert "phase boundary" in messages[0].content


def test_parallel_gate_allows_only_write_todos_or_final_answer():
    middleware = todo_module.TodoListMiddleware(
        system_prompt="test",
        tool_description="test",
        subagent_enabled=True,
        max_concurrent_subagents=2,
    )

    blocked_state = {
        "todo_orchestration": {
            "mode": "parallel_batch",
            "phase": "awaiting_orchestrator",
            "last_write_todos_tool_call_id": "write-1",
            "dispatched_todo_ids": ["todo-1"],
            "dispatched_task_ids": ["task-1"],
        },
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "bash", "args": {"command": "pwd"}, "id": "bash-1", "type": "tool_call"},
                ],
            )
        ],
    }

    blocked = middleware.after_model(blocked_state, SimpleNamespace())

    assert blocked is not None
    blocked_messages = blocked["messages"]
    assert len(blocked_messages) == 1
    assert isinstance(blocked_messages[0], ToolMessage)
    assert blocked_messages[0].tool_call_id == "bash-1"
    assert blocked_messages[0].status == "error"
    assert "must now either call `write_todos` again" in blocked_messages[0].content

    final_state = {
        "todo_orchestration": blocked_state["todo_orchestration"],
        "messages": [AIMessage(content="All batches are complete. Here is the synthesis.")],
    }

    final_result = middleware.after_model(final_state, SimpleNamespace())

    assert final_result == {"todo_orchestration": None}


def test_parallel_gate_clears_before_next_write_todos_batch():
    middleware = todo_module.TodoListMiddleware(
        system_prompt="test",
        tool_description="test",
        subagent_enabled=True,
        max_concurrent_subagents=2,
    )

    state = {
        "todo_orchestration": {
            "mode": "parallel_batch",
            "phase": "awaiting_orchestrator",
            "last_write_todos_tool_call_id": "write-1",
            "dispatched_todo_ids": ["todo-1"],
            "dispatched_task_ids": ["task-1"],
        },
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "write_todos", "args": {"todos": []}, "id": "write-2", "type": "tool_call"},
                ],
            )
        ],
    }

    result = middleware.after_model(state, SimpleNamespace())

    assert result == {"todo_orchestration": None}
