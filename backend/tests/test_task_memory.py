from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

langchain_qdrant_stub = ModuleType("langchain_qdrant")
langchain_qdrant_stub.QdrantVectorStore = object
qdrant_models_stub = ModuleType("qdrant_client.models")
qdrant_models_stub.Distance = SimpleNamespace(COSINE="Cosine")
qdrant_models_stub.VectorParams = object
qdrant_client_stub = ModuleType("qdrant_client")
qdrant_client_stub.QdrantClient = object
retriever_stub = ModuleType("src.community.knowledge_base.retriever")
retriever_stub.get_embedding_model = lambda: object()
retriever_stub.get_qdrant_client = lambda: object()

sys.modules.setdefault("langchain_qdrant", langchain_qdrant_stub)
sys.modules.setdefault("qdrant_client", qdrant_client_stub)
sys.modules.setdefault("qdrant_client.models", qdrant_models_stub)
sys.modules.setdefault("src.community.knowledge_base.retriever", retriever_stub)

from src.agents.middlewares import task_memory_middleware  # noqa: E402
from src.community.knowledge_base import task_memory  # noqa: E402


class _FakeVectorStore:
    added_documents: list[Any] = []
    added_ids: list[str] = []

    def __init__(self, **_kwargs: Any) -> None:
        pass

    def add_documents(self, documents: list[Any], ids: list[str]) -> None:
        self.added_documents.extend(documents)
        self.added_ids.extend(ids)


def _patch_vector_store(monkeypatch: Any) -> None:
    _FakeVectorStore.added_documents = []
    _FakeVectorStore.added_ids = []
    monkeypatch.setattr(
        task_memory,
        "_ensure_task_memory_collection",
        lambda: (object(), object(), "task_memory_test"),
    )
    monkeypatch.setattr(task_memory, "QdrantVectorStore", _FakeVectorStore)


def test_subtask_memory_embeds_result_not_delegated_prompt(monkeypatch: Any) -> None:
    _patch_vector_store(monkeypatch)

    delegated_prompt = (
        "你只负责执行下面这一项 todo，不要接管其他 todo。\n\n"
        "Todo: 梳理盛宣怀与轮船招商局的关系\n\n"
        "要求：先查历史结果，再查原始资料，输出结构化结果。"
    )

    record_id = task_memory.upsert_task_memory_record(
        title="梳理盛宣怀与轮船招商局的关系",
        query=delegated_prompt,
        summary="盛宣怀参与轮船招商局相关事务，并在制度和经营层面产生影响。",
        findings=["其作用需要结合招商局档案继续核对。"],
        citations=["[citation:招商局史料](http://example.test/source)"],
        open_questions=["缺少可核验页码。"],
        task_level="subtask",
        thread_id="thread-1",
        user_id="user-1",
        task_id="task-1",
        raw_result="完整子任务最终输出",
    )

    assert record_id is not None
    assert len(_FakeVectorStore.added_documents) == 1

    document = _FakeVectorStore.added_documents[0]
    assert "你只负责执行下面这一项 todo" not in document.page_content
    assert "要求：先查历史结果" not in document.page_content
    assert "查询:" not in document.page_content
    assert "摘要:" in document.page_content
    assert "盛宣怀参与轮船招商局相关事务" in document.page_content
    assert "关键发现:" in document.page_content
    assert "关键引文:" in document.page_content
    assert document.metadata["query"] == "梳理盛宣怀与轮船招商局的关系"


def test_main_task_memory_still_embeds_user_query(monkeypatch: Any) -> None:
    _patch_vector_store(monkeypatch)

    task_memory.upsert_task_memory_record(
        title="盛宣怀研究",
        query="盛宣怀如何参与近代企业建设？",
        summary="盛宣怀参与电报、轮船、铁路等事业。",
        findings=[],
        citations=[],
        open_questions=[],
        task_level="main",
        thread_id="thread-1",
        user_id="user-1",
        task_id="main:thread-1:0",
    )

    document = _FakeVectorStore.added_documents[0]
    assert "查询: 盛宣怀如何参与近代企业建设？" in document.page_content


class _DecisionModel:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    def invoke(self, _messages: list[Any]) -> SimpleNamespace:
        return SimpleNamespace(content=self.payload)


def test_task_memory_middleware_skips_qdrant_write_when_model_says_skip(monkeypatch: Any) -> None:
    middleware = task_memory_middleware.TaskMemoryMiddleware()
    calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        task_memory_middleware,
        "create_chat_model",
        lambda **_kwargs: _DecisionModel('{"action":"skip","reason":"low value"}'),
    )
    monkeypatch.setattr(
        task_memory_middleware,
        "upsert_task_memory_record",
        lambda **kwargs: calls.append(kwargs) or "record-1",
    )

    state = {
        "messages": [
            HumanMessage(content="这个功能为啥会这样？"),
            AIMessage(content="这是因为当前建议问题生成阶段误读了系统注入文本。"),
        ],
        "current_task_title": "建议问题异常",
        "current_task_human_index": 0,
    }

    result = middleware.after_agent(state, SimpleNamespace(context={"thread_id": "t1", "user_id": "u1"}))

    assert result == {"task_memory_saved_human_index": 0}
    assert calls == []


def test_task_memory_middleware_updates_qdrant_when_model_says_update(monkeypatch: Any) -> None:
    middleware = task_memory_middleware.TaskMemoryMiddleware()
    calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        task_memory_middleware,
        "create_chat_model",
        lambda **_kwargs: _DecisionModel(
            '{"action":"update","target_task_id":"main:old-thread:3","reason":"补充同一主题"}'
        ),
    )
    monkeypatch.setattr(
        task_memory_middleware,
        "upsert_task_memory_record",
        lambda **kwargs: calls.append(kwargs) or "record-1",
    )

    state = {
        "messages": [
            HumanMessage(content="张之洞创办汉阳铁厂等洋务企业时具体面临过哪些困境与失败？"),
            AIMessage(
                content=(
                    "张之洞创办汉阳铁厂时面对资金筹措、技术采购、官商关系和市场需求错配等问题，"
                    "这些因素共同导致早期经营长期承压，并需要后续制度调整才能维持。"
                )
            ),
        ],
        "current_task_title": "张之洞洋务企业困境",
        "current_task_human_index": 0,
        "current_task_memory_matches": [
            {
                "record_id": "record-1",
                "title": "张之洞汉阳铁厂研究",
                "task_id": "main:old-thread:3",
            }
        ],
    }

    result = middleware.after_agent(state, SimpleNamespace(context={"thread_id": "t1", "user_id": "u1"}))

    assert result == {"task_memory_saved_human_index": 0}
    assert len(calls) == 1
    assert calls[0]["title"] == "张之洞汉阳铁厂研究"
    assert calls[0]["task_level"] == "main"


def test_task_memory_middleware_skips_update_when_target_is_not_matched(monkeypatch: Any) -> None:
    middleware = task_memory_middleware.TaskMemoryMiddleware()
    calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        task_memory_middleware,
        "create_chat_model",
        lambda **_kwargs: _DecisionModel(
            '{"action":"update","target_task_id":"main:missing:9","target_title":"不存在的主题"}'
        ),
    )
    monkeypatch.setattr(
        task_memory_middleware,
        "upsert_task_memory_record",
        lambda **kwargs: calls.append(kwargs) or "record-1",
    )

    state = {
        "messages": [
            HumanMessage(content="张之洞创办汉阳铁厂等洋务企业时具体面临过哪些困境与失败？"),
            AIMessage(
                content=(
                    "张之洞创办汉阳铁厂时面对资金筹措、技术采购、官商关系和市场需求错配等问题，"
                    "这些因素共同导致早期经营长期承压，并需要后续制度调整才能维持。"
                )
            ),
        ],
        "current_task_title": "张之洞洋务企业困境",
        "current_task_human_index": 0,
        "current_task_memory_matches": [
            {
                "record_id": "record-1",
                "title": "张之洞汉阳铁厂研究",
                "task_id": "main:old-thread:3",
            }
        ],
    }

    result = middleware.after_agent(state, SimpleNamespace(context={"thread_id": "t1", "user_id": "u1"}))

    assert result == {"task_memory_saved_human_index": 0}
    assert calls == []
