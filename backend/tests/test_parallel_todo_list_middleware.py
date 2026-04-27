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
    assert len(launched_prompts) == 3
    assert len(todos) == 3
    assert todos[0]["status"] == "completed"
    assert todos[1]["status"] == "completed"
    assert todos[2]["status"] == "completed"
    assert command.update["todo_orchestration"] is None
    assert todos[0]["task_id"] == "call-1:" + todos[0]["id"]
    assert todos[2]["task_id"] == "call-1:" + todos[2]["id"]
    assert "result_summary" in todos[0]
    assert any(event["type"] == "task_started" for event in events)
    assert any(event["type"] == "task_completed" for event in events)
    assert "Parallel dispatch summary:" in command.update["messages"][0].content
    assert "最多 2 个并发子任务自动分批执行" in command.update["messages"][0].content


def test_write_todos_auto_promotes_pending_queue_until_all_batches_finish(monkeypatch):
    monkeypatch.setattr(todo_module, "get_stream_writer", lambda: lambda event: None)
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

    launched_order: list[str] = []

    class FakeExecutor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def execute_async(self, prompt: str, task_id: str):
            launched_order.append(task_id)
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
            result=f"done: {task_id}",
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
            {"content": "先执行的任务", "status": "in_progress"},
            {"content": "排队任务一", "status": "pending"},
            {"content": "排队任务二", "status": "pending"},
        ],
        tool_call_id="call-2",
    )

    todos = command.update["todos"]
    assert launched_order == [
        "call-2:" + todos[0]["id"],
        "call-2:" + todos[1]["id"],
        "call-2:" + todos[2]["id"],
    ]
    assert [todo["status"] for todo in todos] == ["completed", "completed", "completed"]
    assert all(todo["task_id"].startswith("call-2:") for todo in todos)
    assert "No subagent batch was dispatched." not in command.update["messages"][0].content


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


def test_write_todos_can_redispatch_completed_todo_with_same_content(monkeypatch):
    launched_task_ids: list[str] = []

    monkeypatch.setattr(todo_module, "get_stream_writer", lambda: lambda event: None)
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
            launched_task_ids.append(task_id)
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
            result=f"rerun: {task_id}",
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
        state={
            "todos": [
                {
                    "id": "todo-same",
                    "content": "读《甲书》：查税制",
                    "status": "completed",
                    "task_id": "call-old:todo-same",
                    "result_summary": "old result",
                }
            ],
            "sandbox": None,
            "thread_data": None,
        },
        context={"thread_id": "thread-1"},
        config={"metadata": {"model_name": "test-model", "trace_id": "trace-1"}},
    )

    command = middleware.tools[0].func(
        runtime=runtime,
        todos=[
            {"content": "读《甲书》：查税制", "status": "in_progress"},
        ],
        tool_call_id="call-new",
    )

    todos = command.update["todos"]
    assert launched_task_ids == ["call-new:todo-same"]
    assert todos[0]["task_id"] == "call-new:todo-same"
    assert todos[0]["status"] == "completed"
    assert todos[0]["result"] == "rerun: call-new:todo-same"
