"""Latency contracts: optional work must not delay or corrupt the main answer."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage


def test_deferred_suggestions_do_not_call_model(monkeypatch):
    from src.agents.middlewares.citation_enforcement_middleware import CitationEnforcementMiddleware
    from src.config.suggestions_config import SuggestionsConfig

    monkeypatch.setattr("src.config.suggestions_config._config", SuggestionsConfig(mode="deferred"))
    model = Mock()
    request = ModelRequest(model=model, messages=[HumanMessage(content="你好")])
    response = CitationEnforcementMiddleware().wrap_model_call(request, lambda _: ModelResponse(result=[AIMessage(content="你好！")]))
    assert "你好！" in response.result[0].content
    model.invoke.assert_not_called()


def test_disabled_task_memory_does_not_start_search(monkeypatch):
    from src.community.knowledge_base import task_memory
    from src.config.task_memory_config import TaskMemoryConfig

    monkeypatch.setattr(task_memory, "get_task_memory_config", lambda: TaskMemoryConfig(enabled=False))
    search = Mock(side_effect=AssertionError("search should not run"))
    monkeypatch.setattr(task_memory, "search_task_memory", search)
    assert task_memory.search_and_prepare_task_memory(query="财政", title="财政", target_state={}) == []
    search.assert_not_called()


def test_suggestions_timeout_returns_fallback(monkeypatch):
    from src.config.suggestions_config import SuggestionsConfig
    from src.gateway.routers import suggestions

    async def delayed(*args, **kwargs):
        await asyncio.sleep(10)

    monkeypatch.setattr(suggestions, "get_suggestions_config", lambda: SuggestionsConfig(timeout_seconds=0.01))
    monkeypatch.setattr(suggestions, "create_chat_model", lambda **_: SimpleNamespace(ainvoke=delayed))
    result = asyncio.run(suggestions.generate_suggestions(suggestions.SuggestionsRequest(question="财政制度", answer="相关史料显示财政制度经历变化。")))
    assert len(result.questions) == 3


def test_recall_deadline_does_not_mutate_live_state(monkeypatch):
    from threading import Event
    from time import monotonic

    from src.community.knowledge_base import task_memory
    from src.config.task_memory_config import TaskMemoryConfig

    task_memory._invalidate_search_cache()
    release = Event()
    finished = Event()

    def slow_search(*args, **kwargs):
        try:
            release.wait(2)
            return [{"metadata": {"summary": "迟到结果"}}]
        finally:
            finished.set()

    monkeypatch.setattr(task_memory, "get_task_memory_config", lambda: TaskMemoryConfig(timeout_seconds=0.02))
    monkeypatch.setattr(task_memory, "search_task_memory", slow_search)
    state = {"messages": []}
    start = monotonic()
    try:
        assert task_memory.search_and_prepare_task_memory(query="slow", title=None, target_state=state) == []
        assert monotonic() - start < 0.5
        assert state == {"messages": []}
    finally:
        release.set()
        assert finished.wait(1)
    assert state == {"messages": []}


def test_first_turn_recall_uses_a_short_wait_and_caches_late_results(monkeypatch):
    from threading import BoundedSemaphore, Event

    from src.community.knowledge_base import task_memory
    from src.config.task_memory_config import TaskMemoryConfig

    task_memory._invalidate_search_cache()
    slots = BoundedSemaphore(1)
    release = Event()
    started = Event()
    calls = []

    def slow_search(*args, **kwargs):
        calls.append(args)
        started.set()
        assert release.wait(1)
        return [{"metadata": {"summary": "可复用的历史结果"}}]

    def prepare(matches, *, target_state):
        target_state["used_recall"] = bool(matches)
        return matches

    monkeypatch.setattr(task_memory, "_search_slots", slots)
    monkeypatch.setattr(task_memory, "get_task_memory_config", lambda: TaskMemoryConfig(timeout_seconds=1, first_turn_timeout_seconds=0.02))
    monkeypatch.setattr(task_memory, "search_task_memory", slow_search)
    monkeypatch.setattr(task_memory, "prepare_task_memory_matches_for_injection", prepare)
    first_state = {}
    try:
        assert task_memory.search_and_prepare_task_memory(query="首轮", title=None, target_state=first_state, first_turn=True) == []
        assert started.is_set()
        assert first_state == {}
    finally:
        release.set()

    assert slots.acquire(timeout=1)
    slots.release()
    next_state = {}
    results = task_memory.search_and_prepare_task_memory(query="首轮", title=None, target_state=next_state)
    assert results[0]["metadata"]["summary"] == "可复用的历史结果"
    assert len(calls) == 1
    assert first_state == {}
    assert next_state == {"used_recall": True}


def test_recall_middleware_uses_short_wait_only_for_the_first_user_message(monkeypatch):
    from src.agents.middlewares import task_memory_middleware

    search = Mock(return_value=[])
    monkeypatch.setattr(task_memory_middleware, "search_and_prepare_task_memory", search)
    middleware = task_memory_middleware.TaskMemoryMiddleware()
    runtime = SimpleNamespace(context={})
    first_turn = [HumanMessage(content="第一个问题")]

    middleware.before_model({"messages": first_turn}, runtime)
    assert search.call_args.kwargs["first_turn"] is True

    followup = [*first_turn, AIMessage(content="上一轮回答"), HumanMessage(content="追问")]
    middleware.before_model({"messages": followup}, runtime)
    assert search.call_args.kwargs["first_turn"] is False


def test_cache_stores_raw_results_before_per_thread_citation_rewrite(monkeypatch):
    from src.community.knowledge_base import task_memory
    from src.config.task_memory_config import TaskMemoryConfig

    task_memory._invalidate_search_cache()
    monkeypatch.setattr(task_memory, "get_task_memory_config", lambda: TaskMemoryConfig())
    raw = [{"metadata": {"summary": "原始编号[citation:1]"}}]
    search = Mock(return_value=raw)
    monkeypatch.setattr(task_memory, "search_task_memory", search)

    def rewrite(matches, *, target_state):
        matches[0]["metadata"]["summary"] = target_state["citation"]
        return matches

    monkeypatch.setattr(task_memory, "prepare_task_memory_matches_for_injection", rewrite)
    first = task_memory.search_and_prepare_task_memory(query="cached", title=None, target_state={"citation": "[citation:2]"})
    second = task_memory.search_and_prepare_task_memory(query="cached", title=None, target_state={"citation": "[citation:9]"})
    assert first[0]["metadata"]["summary"] == "[citation:2]"
    assert second[0]["metadata"]["summary"] == "[citation:9]"
    assert raw[0]["metadata"]["summary"] == "原始编号[citation:1]"
    assert search.call_count == 1
    task_memory._invalidate_search_cache()
    task_memory.search_and_prepare_task_memory(query="cached", title=None, target_state={"citation": "[citation:3]"})
    assert search.call_count == 2


def test_vector_store_validates_only_once_for_repeated_search(monkeypatch):
    from src.community.knowledge_base import task_memory

    client, embeddings = object(), object()
    monkeypatch.setattr(task_memory, "_ensure_task_memory_collection", lambda: (client, embeddings, "reuse-test"))
    store = SimpleNamespace(similarity_search_with_score=Mock(return_value=[]))
    factory = Mock(return_value=store)
    monkeypatch.setattr(task_memory, "QdrantVectorStore", factory)
    task_memory.search_task_memory("第一个问题")
    task_memory.search_task_memory("第二个问题")
    assert factory.call_count == 1
    assert store.similarity_search_with_score.call_count == 2


def test_search_pool_does_not_queue_more_work_when_full(monkeypatch):
    from threading import BoundedSemaphore

    from src.community.knowledge_base import task_memory

    task_memory._invalidate_search_cache()
    slots = BoundedSemaphore(1)
    slots.acquire()
    monkeypatch.setattr(task_memory, "_search_slots", slots)
    search = Mock(side_effect=AssertionError("must not queue"))
    monkeypatch.setattr(task_memory, "search_task_memory", search)
    assert task_memory.search_and_prepare_task_memory(query="busy", title=None, target_state={}) == []
    search.assert_not_called()


def test_async_answer_does_not_wait_for_suggestions(monkeypatch):
    from unittest.mock import AsyncMock

    from src.agents.middlewares.citation_enforcement_middleware import CitationEnforcementMiddleware
    from src.config.suggestions_config import SuggestionsConfig

    monkeypatch.setattr("src.config.suggestions_config._config", SuggestionsConfig(mode="deferred"))
    model = SimpleNamespace(ainvoke=AsyncMock(side_effect=AssertionError("extra LLM call")))
    request = ModelRequest(model=model, messages=[HumanMessage(content="你好")])
    handler = AsyncMock(return_value=ModelResponse(result=[AIMessage(content="你好！")]))
    result = asyncio.run(CitationEnforcementMiddleware().awrap_model_call(request, handler))
    assert "你好！" in result.result[0].content
    model.ainvoke.assert_not_awaited()


def test_suggestions_endpoint_validates_input_and_honors_disabled_mode(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.config.suggestions_config import SuggestionsConfig
    from src.gateway.routers import suggestions

    monkeypatch.setattr(suggestions, "get_suggestions_config", lambda: SuggestionsConfig(mode="disabled"))
    model_factory = Mock(side_effect=AssertionError("disabled must not call provider"))
    monkeypatch.setattr(suggestions, "create_chat_model", model_factory)
    app = FastAPI()
    app.include_router(suggestions.router)
    with TestClient(app) as client:
        assert client.post("/api/models/suggestions", json={"question": "", "answer": "正文"}).status_code == 422
        response = client.post("/api/models/suggestions", json={"question": "问题", "answer": "正文"})
        assert response.status_code == 200
        assert response.json() == {"questions": []}
    model_factory.assert_not_called()


def test_cache_expires_and_is_bounded(monkeypatch):
    from src.community.knowledge_base import task_memory
    from src.config.task_memory_config import TaskMemoryConfig

    task_memory._invalidate_search_cache()
    now = [100.0]
    monkeypatch.setattr(task_memory, "monotonic", lambda: now[0])
    monkeypatch.setattr(task_memory, "get_task_memory_config", lambda: TaskMemoryConfig(cache_ttl_seconds=1, cache_max_entries=1))
    search = Mock(return_value=[])
    monkeypatch.setattr(task_memory, "search_task_memory", search)
    for query in ["one", "two", "one"]:
        task_memory.search_and_prepare_task_memory(query=query, title=None, target_state={})
    assert search.call_count == 3
    now[0] = 102.0
    task_memory.search_and_prepare_task_memory(query="one", title=None, target_state={})
    assert search.call_count == 4
    assert len(task_memory._search_cache) == 1
