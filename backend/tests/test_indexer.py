import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import httpx
from langchain_core.documents import Document

if "qdrant_client" not in sys.modules:
    qdrant_client = ModuleType("qdrant_client")
    qdrant_http = ModuleType("qdrant_client.http")
    qdrant_http_exceptions = ModuleType("qdrant_client.http.exceptions")
    qdrant_models = ModuleType("qdrant_client.models")

    class _DummyQdrantClient:  # pragma: no cover - test import shim
        def __init__(self, *args, **kwargs) -> None:
            pass

    class _DummyDistance:  # pragma: no cover - test import shim
        COSINE = "cosine"

    class _DummyVectorParams:  # pragma: no cover - test import shim
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    class _DummyFilter:  # pragma: no cover - test import shim
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    class _DummyFieldCondition:  # pragma: no cover - test import shim
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    class _DummyMatchAny:  # pragma: no cover - test import shim
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    class _DummyResponseHandlingException(Exception):  # pragma: no cover - test import shim
        def __init__(self, source: Exception) -> None:
            super().__init__(str(source))
            self.source = source

    qdrant_client.QdrantClient = _DummyQdrantClient
    qdrant_client.models = qdrant_models
    qdrant_client.http = qdrant_http
    qdrant_models.Distance = _DummyDistance
    qdrant_models.VectorParams = _DummyVectorParams
    qdrant_models.Filter = _DummyFilter
    qdrant_models.FieldCondition = _DummyFieldCondition
    qdrant_models.MatchAny = _DummyMatchAny
    qdrant_http.exceptions = qdrant_http_exceptions
    qdrant_http_exceptions.ResponseHandlingException = _DummyResponseHandlingException
    sys.modules["qdrant_client"] = qdrant_client
    sys.modules["qdrant_client.http"] = qdrant_http
    sys.modules["qdrant_client.http.exceptions"] = qdrant_http_exceptions
    sys.modules["qdrant_client.models"] = qdrant_models

if "langchain_qdrant" not in sys.modules:
    langchain_qdrant = ModuleType("langchain_qdrant")

    class _DummyQdrantVectorStore:  # pragma: no cover - test import shim
        def __init__(self, *args, **kwargs) -> None:
            pass

        def add_documents(self, *args, **kwargs):
            return None

    langchain_qdrant.QdrantVectorStore = _DummyQdrantVectorStore
    sys.modules["langchain_qdrant"] = langchain_qdrant

if "src.reflection" not in sys.modules:
    reflection = ModuleType("src.reflection")

    def _resolve_variable(value):  # pragma: no cover - test import shim
        return value

    reflection.resolve_variable = _resolve_variable
    sys.modules["src.reflection"] = reflection

from src.community.knowledge_base import indexer


def _set_chunking_config(monkeypatch, chunk_size: int, chunk_overlap: int) -> None:
    monkeypatch.setattr(
        indexer,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(
            chunking=SimpleNamespace(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
        ),
    )


def test_build_chunks_keeps_structured_paragraph_as_single_chunk_when_short(monkeypatch) -> None:
    _set_chunking_config(monkeypatch, chunk_size=80, chunk_overlap=10)

    document = Document(
        page_content="这是一个较短的结构化段落。",
        metadata={
            "source": "/tmp/demo.structured.json",
            "source_type": "structured",
            "page_no": 12,
            "pdf_page_no": 12,
            "paragraph_id": "page-12-p3",
            "paragraph_no": 3,
            "paragraph_no_in_doc": 27,
            "line_start": 101,
            "line_end": 102,
            "bbox": {"x": 1.0, "y": 2.0, "width": 3.0, "height": 4.0},
            "bbox_source": "mineru_grpc",
        },
    )

    chunks = indexer._build_chunks([document], scope="global", thread_id=None)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.page_content == document.page_content
    assert chunk.metadata["paragraph_id"] == "page-12-p3"
    assert chunk.metadata["paragraph_no"] == 3
    assert chunk.metadata["paragraph_no_in_doc"] == 27
    assert chunk.metadata["line_start"] == 101
    assert chunk.metadata["line_end"] == 102
    assert chunk.metadata["paragraph_chunk_index"] is None
    assert chunk.metadata["paragraph_chunk_count"] is None


def test_build_chunks_splits_long_structured_paragraph_but_preserves_metadata(monkeypatch) -> None:
    _set_chunking_config(monkeypatch, chunk_size=20, chunk_overlap=5)

    document = Document(
        page_content="第一部分内容需要被拆分。第二部分内容也需要被拆分。第三部分继续延续。第四部分仍然要保留定位。",
        metadata={
            "source": "/tmp/demo.structured.json",
            "source_type": "structured",
            "page_no": 4,
            "pdf_page_no": 4,
            "paragraph_id": "page-4-p1",
            "paragraph_no": 1,
            "paragraph_no_in_doc": 8,
            "line_start": 31,
            "line_end": 34,
            "bbox_source": "mineru_grpc",
        },
    )

    chunks = indexer._build_chunks([document], scope="global", thread_id=None)

    assert len(chunks) > 1
    assert [chunk.metadata["paragraph_chunk_index"] for chunk in chunks] == list(
        range(1, len(chunks) + 1)
    )
    assert [chunk.metadata["paragraph_chunk_count"] for chunk in chunks] == [len(chunks)] * len(chunks)
    for chunk in chunks:
        assert chunk.metadata["source_type"] == "structured"
        assert chunk.metadata["paragraph_id"] == "page-4-p1"
        assert chunk.metadata["paragraph_no"] == 1
        assert chunk.metadata["paragraph_no_in_doc"] == 8
        assert chunk.metadata["line_start"] == 31
        assert chunk.metadata["line_end"] == 34
        assert len(chunk.page_content) <= 20


def test_upsert_documents_replaces_doc_ids_without_replacing_collection(monkeypatch) -> None:
    _set_chunking_config(monkeypatch, chunk_size=80, chunk_overlap=0)

    original_document = Document(
        page_content="新的个人知识内容",
        metadata={"source": "/tmp/demo.md", "source_type": "text", "doc_id": "uk_1"},
    )

    monkeypatch.setattr(indexer, "_build_chunks", lambda documents, scope, thread_id: documents)
    monkeypatch.setattr(indexer, "get_embedding_model", lambda: SimpleNamespace(embed_query=lambda text: [0.1, 0.2]))

    deleted_doc_ids: list[list[str]] = []
    ensured_collections: list[str] = []
    added_documents: list[Document] = []

    class _Client:
        def delete_collection(self, *args, **kwargs):
            raise AssertionError("upsert should not replace the full collection")

    class _VectorStore:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def add_documents(self, documents, **kwargs):
            assert kwargs["batch_size"] == indexer.UPSERT_BATCH_SIZE
            added_documents.extend(documents)
            return ["p1"]

    monkeypatch.setattr(indexer, "get_qdrant_client", lambda: _Client())
    monkeypatch.setattr(indexer, "_ensure_collection", lambda client, collection_name, embeddings: ensured_collections.append(collection_name))
    monkeypatch.setattr(indexer, "_delete_points_by_doc_ids", lambda client, collection_name, doc_ids: deleted_doc_ids.append(doc_ids))
    monkeypatch.setattr(indexer, "QdrantVectorStore", _VectorStore)

    result = indexer.upsert_documents(
        [original_document],
        collection_name="knowledge_base__user__u1",
        scope="user",
        replace_doc_ids=["uk_1"],
    )

    assert result == 1
    assert ensured_collections == ["knowledge_base__user__u1"]
    assert deleted_doc_ids == [["uk_1"]]
    assert added_documents == [original_document]


def test_upsert_documents_retries_transient_qdrant_disconnect(monkeypatch) -> None:
    _set_chunking_config(monkeypatch, chunk_size=80, chunk_overlap=0)

    original_document = Document(
        page_content="新的个人知识内容",
        metadata={"source": "/tmp/demo.md", "source_type": "text", "doc_id": "uk_1"},
    )

    monkeypatch.setattr(indexer, "_build_chunks", lambda documents, scope, thread_id: documents)
    monkeypatch.setattr(indexer, "get_embedding_model", lambda: SimpleNamespace(embed_query=lambda text: [0.1, 0.2]))
    monkeypatch.setattr(indexer, "sleep", lambda seconds: None)

    deleted_doc_ids: list[list[str]] = []
    ensured_collections: list[str] = []
    attempts: list[list[str]] = []

    class _Client:
        def delete_collection(self, *args, **kwargs):
            raise AssertionError("upsert should not replace the full collection")

    class _VectorStore:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def add_documents(self, documents, **kwargs):
            assert kwargs["batch_size"] == indexer.UPSERT_BATCH_SIZE
            attempts.append(list(kwargs.get("ids") or []))
            if len(attempts) == 1:
                raise indexer.ResponseHandlingException(
                    httpx.RemoteProtocolError("Server disconnected without sending a response.")
                )
            return ["p1"]

    monkeypatch.setattr(indexer, "get_qdrant_client", lambda: _Client())
    monkeypatch.setattr(indexer, "_ensure_collection", lambda client, collection_name, embeddings: ensured_collections.append(collection_name))
    monkeypatch.setattr(indexer, "_delete_points_by_doc_ids", lambda client, collection_name, doc_ids: deleted_doc_ids.append(doc_ids))
    monkeypatch.setattr(indexer, "QdrantVectorStore", _VectorStore)

    result = indexer.upsert_documents(
        [original_document],
        collection_name="knowledge_base__user__u1",
        scope="user",
        replace_doc_ids=["uk_1"],
    )

    assert result == 1
    assert ensured_collections == ["knowledge_base__user__u1"]
    assert deleted_doc_ids == [["uk_1"]]
    assert len(attempts) == 2
    assert attempts[0] == attempts[1]
    assert len(attempts[0]) == 1


def test_delete_documents_by_doc_ids_uses_filtered_delete(monkeypatch) -> None:
    captured = {}

    class _Client:
        def delete(self, *, collection_name, points_selector, wait):
            captured["collection_name"] = collection_name
            captured["points_selector"] = points_selector
            captured["wait"] = wait

    monkeypatch.setattr(indexer, "get_qdrant_client", lambda: _Client())

    indexer.delete_documents_by_doc_ids("knowledge_base__user__u1", ["uk_1", "uk_2"])

    assert captured["collection_name"] == "knowledge_base__user__u1"
    assert captured["wait"] is True


def test_upsert_global_knowledge_record_resumes_from_checkpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        indexer,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(
            docs_path="/tmp/knowledge/docs",
            qdrant=SimpleNamespace(collection_name="knowledge_base"),
            chunking=SimpleNamespace(chunk_size=80, chunk_overlap=0),
        ),
    )

    original_document = Document(
        page_content="全局知识内容",
        metadata={"source": "/tmp/demo.structured.json", "source_type": "structured", "doc_id": "gk_1"},
    )
    chunks = [
        Document(page_content=f"chunk-{index}", metadata={"source": "/tmp/demo.structured.json", "doc_id": "gk_1"})
        for index in range(5)
    ]

    monkeypatch.setattr(indexer, "resolve_project_path", lambda path: Path("/tmp/knowledge/docs"))
    monkeypatch.setattr(
        indexer,
        "_load_global_documents_for_sources",
        lambda source_filenames, docs_root, records_by_source_filename: ([original_document], ["doc-1"]),
    )
    monkeypatch.setattr(indexer, "_load_global_records_by_source_filename", lambda docs_root: {"a.pdf": {}})
    monkeypatch.setattr(indexer, "_build_chunks", lambda documents, scope, thread_id: chunks)
    monkeypatch.setattr(indexer, "get_embedding_model", lambda: SimpleNamespace(embed_query=lambda text: [0.1, 0.2]))

    deleted_doc_ids: list[list[str]] = []
    progress: list[tuple[int, int, str]] = []
    added_payloads: list[list[str]] = []

    class _Client:
        pass

    class _VectorStore:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def add_documents(self, documents, **kwargs):
            added_payloads.append([document.page_content for document in documents])
            return ["p1"]

    fingerprint = indexer._chunk_fingerprint(chunks)

    monkeypatch.setattr(indexer, "get_qdrant_client", lambda: _Client())
    monkeypatch.setattr(indexer, "_ensure_collection", lambda client, collection_name, embeddings: None)
    monkeypatch.setattr(indexer, "_delete_points_by_doc_ids", lambda client, collection_name, doc_ids: deleted_doc_ids.append(doc_ids))
    monkeypatch.setattr(indexer, "QdrantVectorStore", _VectorStore)

    total_chunks, returned_fingerprint = indexer.upsert_global_knowledge_record(
        "a.pdf",
        resume_chunk_index=2,
        expected_fingerprint=fingerprint,
        on_batch_complete=lambda next_chunk_index, total, content_fingerprint: progress.append(
            (next_chunk_index, total, content_fingerprint)
        ),
    )

    assert total_chunks == 5
    assert returned_fingerprint == fingerprint
    assert deleted_doc_ids == []
    assert added_payloads == [["chunk-2", "chunk-3", "chunk-4"]]
    assert progress == [(5, 5, fingerprint)]
