import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.documents import Document

if "qdrant_client" not in sys.modules:
    qdrant_client = ModuleType("qdrant_client")
    qdrant_models = ModuleType("qdrant_client.models")

    class _DummyQdrantClient:  # pragma: no cover - test import shim
        def __init__(self, *args, **kwargs) -> None:
            pass

        def delete_collection(self, *args, **kwargs) -> None:
            return None

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

    qdrant_client.QdrantClient = _DummyQdrantClient
    qdrant_client.models = qdrant_models
    qdrant_models.Distance = _DummyDistance
    qdrant_models.VectorParams = _DummyVectorParams
    qdrant_models.Filter = _DummyFilter
    qdrant_models.FieldCondition = _DummyFieldCondition
    qdrant_models.MatchAny = _DummyMatchAny
    sys.modules["qdrant_client"] = qdrant_client
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

import src.community.knowledge_base.indexer as indexer_module
import src.community.knowledge_base.retriever as retriever_module
import src.community.knowledge_base.user_store as user_store_module
import src.config.paths as paths_module
from src.config.paths import Paths

_USER_KNOWLEDGE_ROUTER_SPEC = importlib.util.spec_from_file_location(
    "test_user_knowledge_router_module",
    Path(__file__).parent.parent / "src/gateway/routers/user_knowledge.py",
)
user_knowledge_router = importlib.util.module_from_spec(_USER_KNOWLEDGE_ROUTER_SPEC)
assert _USER_KNOWLEDGE_ROUTER_SPEC and _USER_KNOWLEDGE_ROUTER_SPEC.loader
_USER_KNOWLEDGE_ROUTER_SPEC.loader.exec_module(user_knowledge_router)


def test_paths_create_user_knowledge_dirs_and_validate_user_id(tmp_path) -> None:
    paths = Paths(tmp_path)
    paths.ensure_user_knowledge_dirs("user_123")

    assert paths.user_knowledge_docs_dir("user_123").exists()
    assert paths.user_knowledge_ingestion_dir("user_123").exists()
    assert paths.user_knowledge_catalog_dir("user_123").exists()

    try:
        paths.user_dir("../bad")
    except ValueError as exc:
        assert "Invalid user_id" in str(exc)
    else:  # pragma: no cover - defensive failure
        raise AssertionError("expected invalid user_id to raise")


def test_rebuild_user_knowledge_index_indexes_upload_and_skips_import_ref(tmp_path, monkeypatch) -> None:
    paths = Paths(tmp_path)
    monkeypatch.setattr(paths_module, "_paths", paths)
    paths.ensure_user_knowledge_dirs("user_1")

    upload_path = paths.user_knowledge_ingestion_dir("user_1") / "notes.md.structured.json"
    upload_path.write_text("{}", encoding="utf-8")
    upload_record = user_store_module.build_user_upload_record(
        user_id="user_1",
        source_filename="notes.md",
        size=12,
        content_type="text/markdown",
    )
    upload_record["parse_status"] = "indexed"
    upload_record["indexable"] = True
    upload_record["index_target_filename"] = upload_path.name
    upload_record["index_target_path"] = str(upload_path)
    user_store_module.save_user_record("user_1", upload_record)

    import_record = user_store_module.build_user_import_ref_record(
        user_id="user_1",
        title="Global Book",
        origin_doc_id="global-book",
        origin_filename="global-book.pdf",
    )
    user_store_module.save_user_record("user_1", import_record)

    monkeypatch.setattr(
        indexer_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(
            qdrant=SimpleNamespace(collection_name="knowledge_base"),
            chunking=SimpleNamespace(chunk_size=128, chunk_overlap=0),
        ),
    )
    monkeypatch.setattr(indexer_module, "get_qdrant_client", lambda: SimpleNamespace(delete_collection=lambda **kwargs: None))

    def fake_load_documents(paths_to_load):
        return [
            Document(
                page_content="我的个人知识",
                metadata={
                    "source": str(upload_path),
                    "source_type": "structured",
                },
            )
        ] if paths_to_load else []

    captured = {}

    def fake_index_documents(documents, collection_name, scope, thread_id=None):
        captured["documents"] = documents
        return len(documents)

    monkeypatch.setattr(indexer_module, "_load_documents_from_paths", fake_load_documents)
    monkeypatch.setattr(indexer_module, "index_documents", fake_index_documents)

    result = indexer_module.rebuild_user_knowledge_index("user_1")

    assert result == 1
    assert len(captured["documents"]) == 1
    assert captured["documents"][0].metadata["scope"] == "user"
    assert captured["documents"][0].metadata["doc_id"] == upload_record["id"]
    assert captured["documents"][0].metadata["source_kind"] == "upload"


def test_retriever_prioritizes_user_results_over_thread_and_global(monkeypatch) -> None:
    monkeypatch.setattr(
        retriever_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(
            qdrant=SimpleNamespace(collection_name="knowledge_base"),
            retrieval=SimpleNamespace(top_k=5, score_threshold=0.0),
        ),
    )
    monkeypatch.setattr(retriever_module, "get_qdrant_client", lambda: object())
    monkeypatch.setattr(retriever_module, "get_embedding_model", lambda: object())
    monkeypatch.setattr(retriever_module, "lexical_search_documents", lambda *args, **kwargs: [])

    retriever = retriever_module.KnowledgeBaseRetriever()

    def fake_search_collection(collection_name: str, query: str, doc_ids=None):
        if "__user__" in collection_name:
            return [
                {
                    "content": "用户知识",
                    "score": 1.0,
                    "filename": "user.md",
                    "source": "user",
                    "page": None,
                    "source_type": "structured",
                    "metadata": {"scope": "user", "source_kind": "upload", "doc_id": "user-doc"},
                }
            ]
        if "__thread__" in collection_name:
            return [
                {
                    "content": "会话知识",
                    "score": 1.0,
                    "filename": "thread.md",
                    "source": "thread",
                    "page": None,
                    "source_type": "structured",
                    "metadata": {"scope": "thread", "source_kind": "thread_upload", "doc_id": "thread-doc"},
                }
            ]
        return [
            {
                "content": "公共知识",
                "score": 1.0,
                "filename": "global.md",
                "source": "global",
                "page": None,
                "source_type": "structured",
                "metadata": {"scope": "global", "source_kind": "global_document", "doc_id": "global-doc"},
            }
        ]

    monkeypatch.setattr(retriever, "_search_collection", fake_search_collection)

    results = retriever.search("query", thread_id="thread-1", user_id="user-1")

    assert [result["content"] for result in results[:3]] == ["用户知识", "会话知识", "公共知识"]


def test_user_knowledge_router_upload_and_import(tmp_path, monkeypatch) -> None:
    paths = Paths(tmp_path)
    monkeypatch.setattr(paths_module, "_paths", paths)
    paths.ensure_user_knowledge_dirs("user_1")

    global_docs_dir = tmp_path / "knowledge" / "docs"
    global_docs_dir.mkdir(parents=True)
    (global_docs_dir / "global-book.md").write_text("# Global\ncontent", encoding="utf-8")

    monkeypatch.setattr(
        user_knowledge_router,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(
            docs_path=str(global_docs_dir),
            qdrant=SimpleNamespace(collection_name="knowledge_base"),
        ),
    )
    monkeypatch.setattr(user_knowledge_router, "upsert_user_knowledge_records", lambda user_id, record_ids: 1)
    monkeypatch.setattr(user_knowledge_router, "mark_user_records_indexed", lambda user_id: None)
    monkeypatch.setattr(user_knowledge_router, "get_qdrant_client", lambda: SimpleNamespace(get_collection=lambda name: SimpleNamespace(points_count=1)))

    app = FastAPI()
    app.include_router(user_knowledge_router.router)
    client = TestClient(app)

    upload_response = client.post(
        "/api/users/user_1/knowledge/upload",
        files={"files": ("notes.md", b"# Notes\npersonal", "text/markdown")},
    )
    assert upload_response.status_code == 200
    assert upload_response.json()["records"][0]["filename"] == "notes.md"

    import_response = client.post(
        "/api/users/user_1/knowledge/import-from-global",
        json={"filename": "global-book.md"},
    )
    assert import_response.status_code == 200
    assert import_response.json()["record"]["source_kind"] == "import_ref"

    list_response = client.get("/api/users/user_1/knowledge/list")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["count"] == 2


def test_user_knowledge_router_returns_derived_editor_content(tmp_path, monkeypatch) -> None:
    paths = Paths(tmp_path)
    monkeypatch.setattr(paths_module, "_paths", paths)
    paths.ensure_user_knowledge_dirs("user_1")

    record = user_store_module.build_user_derived_record(
        user_id="user_1",
        source_kind="excerpt",
        title="盐税摘录",
        source_filename="uk_excerpt.md",
        size=0,
        origin_scope="global",
        origin_doc_id="global-book",
        origin_filename="global-book.pdf",
        origin_anchor={
            "pdf_page_no": 12,
            "paragraph_no": 3,
            "text": "这是原文段落",
        },
    )
    user_store_module.persist_user_text_document(
        "user_1",
        "uk_excerpt.md",
        "# 盐税摘录\n\n来源：global-book.pdf\n定位：PDF 第 12 页 · 第 3 段\n\n## 原文摘录\n\n> 这是原文段落\n\n## 我的摘抄笔记\n\n这是我的笔记\n",
    )
    structured_path = paths.user_knowledge_ingestion_dir("user_1") / "uk_excerpt.md.structured.json"
    structured_path.write_text("{}", encoding="utf-8")
    record["parse_status"] = "indexed"
    record["structured_filename"] = structured_path.name
    record["structured_path"] = str(structured_path)
    record["index_target_filename"] = structured_path.name
    record["index_target_path"] = str(structured_path)
    user_store_module.save_user_record("user_1", record)

    app = FastAPI()
    app.include_router(user_knowledge_router.router)
    client = TestClient(app)

    response = client.get(f"/api/users/user_1/knowledge/{record['id']}/content")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "derived"
    assert payload["editable"] is True
    assert payload["locked_excerpt"] == "这是原文段落"
    assert payload["editable_content"] == "这是我的笔记"
    assert payload["location_label"] == "PDF 第 12 页 · 第 3 段"


def test_user_knowledge_router_updates_text_content_and_reindexes(tmp_path, monkeypatch) -> None:
    paths = Paths(tmp_path)
    monkeypatch.setattr(paths_module, "_paths", paths)
    paths.ensure_user_knowledge_dirs("user_1")

    record = user_store_module.build_user_derived_record(
        user_id="user_1",
        source_kind="excerpt",
        title="旧标题",
        source_filename="uk_excerpt.md",
        size=0,
        origin_scope="global",
        origin_doc_id="global-book",
        origin_filename="global-book.pdf",
        origin_anchor={
            "pdf_page_no": 9,
            "paragraph_no": 1,
            "text": "锁定原文",
        },
    )
    user_store_module.persist_user_text_document(
        "user_1",
        "uk_excerpt.md",
        "# 旧标题\n\n来源：global-book.pdf\n定位：PDF 第 9 页 · 第 1 段\n\n## 原文摘录\n\n> 锁定原文\n\n## 我的摘抄笔记\n\n旧内容\n",
    )
    structured_path = paths.user_knowledge_ingestion_dir("user_1") / "uk_excerpt.md.structured.json"
    structured_path.write_text("{}", encoding="utf-8")
    record["parse_status"] = "indexed"
    record["structured_filename"] = structured_path.name
    record["structured_path"] = str(structured_path)
    record["index_target_filename"] = structured_path.name
    record["index_target_path"] = str(structured_path)
    user_store_module.save_user_record("user_1", record)

    upsert_calls: list[tuple[str, list[str]]] = []
    indexed_calls: list[str] = []

    monkeypatch.setattr(
        user_knowledge_router,
        "upsert_user_knowledge_records",
        lambda user_id, record_ids: upsert_calls.append((user_id, record_ids)) or 1,
    )
    monkeypatch.setattr(user_knowledge_router, "mark_user_records_indexed", lambda user_id: indexed_calls.append(user_id))

    app = FastAPI()
    app.include_router(user_knowledge_router.router)
    client = TestClient(app)

    response = client.put(
        f"/api/users/user_1/knowledge/{record['id']}/content",
        json={"title": "新标题", "content": "新笔记"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "新标题"
    assert payload["editable_content"] == "新笔记"
    assert payload["locked_excerpt"] == "锁定原文"
    assert upsert_calls == [("user_1", [str(record["id"])])]
    assert indexed_calls == ["user_1"]

    updated_record = user_store_module.load_user_record("user_1", str(record["id"]))
    assert updated_record is not None
    assert updated_record["title"] == "新标题"

    saved_content = (paths.user_knowledge_docs_dir("user_1") / "uk_excerpt.md").read_text(encoding="utf-8")
    assert "## 原文摘录" in saved_content
    assert "> 锁定原文" in saved_content
    assert "## 我的摘抄笔记" in saved_content
    assert "新笔记" in saved_content


def test_user_knowledge_router_creates_plain_note_and_returns_text_editor(tmp_path, monkeypatch) -> None:
    paths = Paths(tmp_path)
    monkeypatch.setattr(paths_module, "_paths", paths)
    paths.ensure_user_knowledge_dirs("user_1")

    upsert_calls: list[tuple[str, list[str]]] = []
    indexed_calls: list[str] = []

    monkeypatch.setattr(
        user_knowledge_router,
        "upsert_user_knowledge_records",
        lambda user_id, record_ids: upsert_calls.append((user_id, record_ids)) or 1,
    )
    monkeypatch.setattr(user_knowledge_router, "mark_user_records_indexed", lambda user_id: indexed_calls.append(user_id))

    app = FastAPI()
    app.include_router(user_knowledge_router.router)
    client = TestClient(app)

    create_response = client.post(
        "/api/users/user_1/knowledge/derived",
        json={"title": "会议记录", "content": "", "source_kind": "note"},
    )

    assert create_response.status_code == 200
    payload = create_response.json()
    assert payload["record"]["source_kind"] == "note"
    assert upsert_calls == [("user_1", [payload["record"]["id"]])]
    assert indexed_calls == ["user_1"]

    record_id = payload["record"]["id"]
    content_response = client.get(f"/api/users/user_1/knowledge/{record_id}/content")

    assert content_response.status_code == 200
    content_payload = content_response.json()
    assert content_payload["mode"] == "text"
    assert content_payload["editable"] is True
    assert content_payload["title"] == "会议记录"
    assert content_payload["editable_content"] == ""

    saved_content = (paths.user_knowledge_docs_dir("user_1") / f"{record_id}.md").read_text(encoding="utf-8")
    assert saved_content == "# 会议记录\n"


def test_user_knowledge_router_delete_tolerates_non_file_artifacts(tmp_path, monkeypatch) -> None:
    paths = Paths(tmp_path)
    monkeypatch.setattr(paths_module, "_paths", paths)
    paths.ensure_user_knowledge_dirs("user_1")

    record = user_store_module.build_user_derived_record(
        user_id="user_1",
        source_kind="note",
        title="待删除笔记",
        source_filename="uk_note.md",
        size=0,
        origin_scope=None,
        origin_doc_id=None,
        origin_filename=None,
    )
    record["source_path"] = str(paths.user_knowledge_docs_dir("user_1"))
    record["structured_path"] = str(paths.user_knowledge_ingestion_dir("user_1"))
    user_store_module.save_user_record("user_1", record)

    deleted_calls: list[tuple[str, list[str]]] = []
    indexed_calls: list[str] = []
    monkeypatch.setattr(
        user_knowledge_router,
        "delete_user_knowledge_records",
        lambda user_id, record_ids: deleted_calls.append((user_id, record_ids)),
    )
    monkeypatch.setattr(user_knowledge_router, "mark_user_records_indexed", lambda user_id: indexed_calls.append(user_id))

    app = FastAPI()
    app.include_router(user_knowledge_router.router)
    client = TestClient(app)

    response = client.delete(f"/api/users/user_1/knowledge/{record['id']}")

    assert response.status_code == 200
    assert user_store_module.load_user_record("user_1", str(record["id"])) is None
    assert deleted_calls == [("user_1", [str(record["id"])])]
    assert indexed_calls == ["user_1"]
