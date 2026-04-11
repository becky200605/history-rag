import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from fastapi import HTTPException

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

        def similarity_search_with_score(self, *args, **kwargs):
            return []

    langchain_qdrant.QdrantVectorStore = _DummyQdrantVectorStore
    sys.modules["langchain_qdrant"] = langchain_qdrant

if "src.reflection" not in sys.modules:
    reflection = ModuleType("src.reflection")

    def _resolve_variable(value):  # pragma: no cover - test import shim
        return value

    def _resolve_class(value):  # pragma: no cover - test import shim
        return value

    reflection.resolve_variable = _resolve_variable
    reflection.resolve_class = _resolve_class
    sys.modules["src.reflection"] = reflection

if "src.community.knowledge_base.translation_grpc" not in sys.modules:
    translation_grpc = ModuleType("src.community.knowledge_base.translation_grpc")

    def _translate_blocks_to_chinese_via_grpc(blocks):  # pragma: no cover - test import shim
        return [{"id": block["id"], "translation": block["text"]} for block in blocks]

    translation_grpc.translate_blocks_to_chinese_via_grpc = _translate_blocks_to_chinese_via_grpc
    sys.modules["src.community.knowledge_base.translation_grpc"] = translation_grpc

_KNOWLEDGE_ROUTER_SPEC = importlib.util.spec_from_file_location(
    "test_knowledge_router_module",
    Path(__file__).parent.parent / "src/gateway/routers/knowledge.py",
)
knowledge_router = importlib.util.module_from_spec(_KNOWLEDGE_ROUTER_SPEC)
assert _KNOWLEDGE_ROUTER_SPEC and _KNOWLEDGE_ROUTER_SPEC.loader
_KNOWLEDGE_ROUTER_SPEC.loader.exec_module(knowledge_router)


def test_process_single_global_embedding_failure_is_isolated(monkeypatch) -> None:
    records = {
        "a.pdf": {
            "source_filename": "a.pdf",
            "indexable": True,
            "parse_status": "queued_embedding",
            "index_target_path": "/tmp/a.json",
            "error": None,
        },
        "b.pdf": {
            "source_filename": "b.pdf",
            "indexable": True,
            "parse_status": "queued_embedding",
            "index_target_path": "/tmp/b.json",
            "error": None,
        },
    }
    calls: list[list[str]] = []

    monkeypatch.setattr(
        knowledge_router,
        "_load_global_record",
        lambda filename: dict(records[filename]) if filename in records else None,
    )
    monkeypatch.setattr(
        knowledge_router,
        "_save_global_record",
        lambda filename, record: records.__setitem__(filename, dict(record)),
    )
    monkeypatch.setattr(knowledge_router, "_list_global_records", lambda: [dict(record) for record in records.values()])
    monkeypatch.setattr(knowledge_router, "_acquire_knowledge_operation_lock", lambda: None)
    monkeypatch.setattr(knowledge_router, "_release_knowledge_operation_lock", lambda: None)

    def fake_upsert(
        filename: str,
        *,
        resume_chunk_index: int = 0,
        expected_fingerprint: str | None = None,
        on_batch_complete=None,
    ) -> tuple[int, str]:
        calls.append([filename])
        if filename == "a.pdf" and on_batch_complete is not None:
            on_batch_complete(16, 30, "fp-a")
        if filename == "a.pdf":
            raise RuntimeError("boom")
        return 3, "fp-b"

    monkeypatch.setattr(knowledge_router, "upsert_global_knowledge_record", fake_upsert)

    def fake_mark_indexed(source_filenames: list[str] | None = None) -> None:
        for filename in source_filenames or []:
            record = dict(records[filename])
            record["parse_status"] = "indexed"
            records[filename] = record

    monkeypatch.setattr(knowledge_router, "_mark_global_records_indexed", fake_mark_indexed)

    knowledge_router._process_single_global_embedding("a.pdf")

    assert calls == [["a.pdf"]]
    assert records["a.pdf"]["parse_status"] == "index_failed"
    assert records["a.pdf"]["error"] == "reindex failed: boom"
    assert records["a.pdf"]["embedding_checkpoint"] == {
        "next_chunk_index": 16,
        "total_chunks": 30,
        "content_fingerprint": "fp-a",
        "batch_size": knowledge_router._get_upsert_batch_size(),
    }
    assert records["b.pdf"]["parse_status"] == "queued_embedding"
    assert records["b.pdf"]["error"] is None

    knowledge_router._process_single_global_embedding("b.pdf")

    assert calls == [["a.pdf"], ["b.pdf"]]
    assert records["b.pdf"]["parse_status"] == "indexed"
    assert records["b.pdf"]["error"] is None


def test_process_single_global_embedding_requeues_only_current_file_on_lock_conflict(
    monkeypatch,
) -> None:
    records = {
        "a.pdf": {
            "source_filename": "a.pdf",
            "indexable": True,
            "parse_status": "queued_embedding",
            "index_target_path": "/tmp/a.json",
            "error": None,
        },
    }
    requeued: list[str] = []

    monkeypatch.setattr(
        knowledge_router,
        "_load_global_record",
        lambda filename: dict(records[filename]) if filename in records else None,
    )
    monkeypatch.setattr(
        knowledge_router,
        "_save_global_record",
        lambda filename, record: records.__setitem__(filename, dict(record)),
    )
    monkeypatch.setattr(
        knowledge_router,
        "_acquire_knowledge_operation_lock",
        lambda: (_ for _ in ()).throw(HTTPException(status_code=409, detail="busy")),
    )
    monkeypatch.setattr(knowledge_router, "_enqueue_global_embedding", requeued.append)

    knowledge_router._process_single_global_embedding("a.pdf")

    assert requeued == ["a.pdf"]
    assert records["a.pdf"]["parse_status"] == "queued_embedding"
    assert records["a.pdf"]["error"] is None


def test_process_single_global_embedding_resumes_from_checkpoint(monkeypatch, tmp_path) -> None:
    target_path = tmp_path / "a.json"
    target_path.write_text("{}", encoding="utf-8")
    records = {
        "a.pdf": {
            "source_filename": "a.pdf",
            "indexable": True,
            "parse_status": "index_failed",
            "index_target_path": str(target_path),
            "error": "reindex failed: boom",
            "embedding_checkpoint": {
                "next_chunk_index": 16,
                "total_chunks": 30,
                "content_fingerprint": "fp-a",
                "batch_size": 16,
            },
        },
    }
    captured: list[tuple[str, int, str | None]] = []

    monkeypatch.setattr(
        knowledge_router,
        "_load_global_record",
        lambda filename: dict(records[filename]) if filename in records else None,
    )
    monkeypatch.setattr(
        knowledge_router,
        "_save_global_record",
        lambda filename, record: records.__setitem__(filename, dict(record)),
    )
    monkeypatch.setattr(knowledge_router, "_list_global_records", lambda: [dict(record) for record in records.values()])
    monkeypatch.setattr(knowledge_router, "_acquire_knowledge_operation_lock", lambda: None)
    monkeypatch.setattr(knowledge_router, "_release_knowledge_operation_lock", lambda: None)

    def fake_upsert(
        filename: str,
        *,
        resume_chunk_index: int = 0,
        expected_fingerprint: str | None = None,
        on_batch_complete=None,
    ) -> tuple[int, str]:
        captured.append((filename, resume_chunk_index, expected_fingerprint))
        if on_batch_complete is not None:
            on_batch_complete(30, 30, "fp-a")
        return 30, "fp-a"

    monkeypatch.setattr(knowledge_router, "upsert_global_knowledge_record", fake_upsert)

    knowledge_router._process_single_global_embedding("a.pdf")

    assert captured == [("a.pdf", 16, "fp-a")]
    assert records["a.pdf"]["parse_status"] == "indexed"
    assert records["a.pdf"]["error"] is None
    assert records["a.pdf"]["embedding_checkpoint"] is None


async def _call_retry_global_knowledge_file(filename: str):
    return await knowledge_router.retry_global_knowledge_file(filename)


def test_retry_global_knowledge_file_requeues_indexed_document_for_embedding(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "indexed.pdf"
    source_path.write_text("pdf", encoding="utf-8")
    records = {
        "indexed.pdf": {
            "source_filename": "indexed.pdf",
            "indexable": True,
            "parse_status": "indexed",
            "index_target_path": "/tmp/indexed.structured.json",
            "error": None,
        },
    }
    enqueued: list[str] = []

    monkeypatch.setattr(
        knowledge_router,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(enabled=True),
    )
    monkeypatch.setattr(
        knowledge_router,
        "_find_global_record",
        lambda filename: dict(records[filename]) if filename in records else None,
    )
    monkeypatch.setattr(knowledge_router, "get_global_docs_dir", lambda: tmp_path)
    monkeypatch.setattr(
        knowledge_router,
        "_save_global_record",
        lambda filename, record: records.__setitem__(filename, dict(record)),
    )
    monkeypatch.setattr(knowledge_router, "_ensure_global_queue_workers_started", lambda: None)
    monkeypatch.setattr(knowledge_router, "_enqueue_global_embedding", enqueued.append)

    import asyncio

    result = asyncio.run(_call_retry_global_knowledge_file("indexed.pdf"))

    assert result["success"] is True
    assert "重新加入入库队列" in result["message"]
    assert records["indexed.pdf"]["parse_status"] == "queued_embedding"
    assert enqueued == ["indexed.pdf"]


def test_update_global_knowledge_metadata_updates_hints(monkeypatch) -> None:
    record = {
        "source_filename": "demo.pdf",
        "display_title": "演示文档",
        "hints": {
            "language_hint": "unknown",
            "layout_hint": "horizontal",
            "document_type_hint": "book",
        },
    }
    saved_records: list[dict] = []

    monkeypatch.setattr(
        knowledge_router,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(
            enabled=True,
            book_metadata=SimpleNamespace(model_name="demo-model", front_page_limit=10, max_excerpt_chars=1200),
        ),
    )
    monkeypatch.setattr(
        knowledge_router,
        "_load_structured_payload_for_metadata",
        lambda filename: (
            {"pages": [{"paragraphs": []}]},
            record,
            Path("/tmp"),
        ),
    )
    monkeypatch.setattr(knowledge_router, "load_book_metadata_for_source", lambda docs_dir, filename: None)
    monkeypatch.setattr(
        knowledge_router,
        "build_book_metadata_prompt_input",
        lambda *args, **kwargs: {"title": "demo"},
    )
    monkeypatch.setattr(
        knowledge_router,
        "build_book_metadata_record",
        lambda **kwargs: SimpleNamespace(suggestion=None, prompt_input=kwargs.get("prompt_input"), model_name=kwargs.get("model_name")),
    )
    monkeypatch.setattr(knowledge_router, "save_book_metadata", lambda docs_dir, filename, book_metadata_record: None)
    monkeypatch.setattr(
        knowledge_router,
        "_save_global_record",
        lambda filename, payload: saved_records.append(dict(payload)),
    )
    monkeypatch.setattr(
        knowledge_router,
        "_load_global_book_metadata",
        lambda filename: {
            "type": None,
            "categories": [],
            "eras": [],
            "regions": [],
            "keywords": [],
            "summary": None,
            "tags": [],
            "language_hint": "zh-Hant",
            "layout_hint": "vertical",
            "document_type_hint": "ancient_book",
        },
    )

    import asyncio

    result = asyncio.run(
        knowledge_router.update_global_knowledge_metadata(
            "demo.pdf",
            knowledge_router.KnowledgeMetadataUpdateRequest(
                layout_hint="vertical",
                language_hint="zh-Hant",
                document_type_hint="ancient_book",
            ),
        )
    )

    assert result["metadata"]["layout_hint"] == "vertical"
    assert saved_records[-1]["hints"]["layout_hint"] == "vertical"
    assert saved_records[-1]["hints"]["language_hint"] == "zh-Hant"
    assert saved_records[-1]["hints"]["document_type_hint"] == "ancient_book"


def test_load_global_book_metadata_uses_explicit_folder(monkeypatch, tmp_path) -> None:
    suggestion = SimpleNamespace(
        type=knowledge_router.MetadataField(value="core", confidence=0.9, evidence="demo"),
        folder=knowledge_router.MetadataField(value="财政史/清代", confidence=0.8, evidence="demo"),
        categories=[knowledge_router.MetadataField(value="财政史", confidence=0.9, evidence="demo")],
        eras=[],
        regions=[],
        keywords=[],
        summary=None,
    )
    record = SimpleNamespace(suggestion=suggestion)

    monkeypatch.setattr(knowledge_router, "get_global_docs_dir", lambda: tmp_path)
    monkeypatch.setattr(knowledge_router, "load_book_metadata_for_source", lambda docs_dir, filename: record)
    monkeypatch.setattr(knowledge_router, "_find_global_record", lambda filename: {"hints": {}})

    result = knowledge_router._load_global_book_metadata("demo.pdf")

    assert result["folder"] == "财政史/清代"


def test_load_global_book_metadata_falls_back_to_first_tag_for_legacy_records(monkeypatch, tmp_path) -> None:
    suggestion = SimpleNamespace(
        type=None,
        folder=None,
        categories=[knowledge_router.MetadataField(value="制度史", confidence=0.9, evidence="demo")],
        eras=[knowledge_router.MetadataField(value="明清", confidence=0.8, evidence="demo")],
        regions=[],
        keywords=[],
        summary=None,
    )
    record = SimpleNamespace(suggestion=suggestion)

    monkeypatch.setattr(knowledge_router, "get_global_docs_dir", lambda: tmp_path)
    monkeypatch.setattr(knowledge_router, "load_book_metadata_for_source", lambda docs_dir, filename: record)
    monkeypatch.setattr(knowledge_router, "_find_global_record", lambda filename: {"hints": {}})

    result = knowledge_router._load_global_book_metadata("legacy.pdf")

    assert result["tags"] == ["制度史", "明清"]
    assert result["folder"] == "制度史"
