from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

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

from src.community.knowledge_base import task_memory


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
