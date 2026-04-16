import sys
from types import ModuleType, SimpleNamespace

import src.community.knowledge_base.catalog as catalog_module
import src.community.knowledge_base.tools as tools_module
from src.community.knowledge_base.book_metadata import build_book_metadata_record, save_book_metadata
from src.community.knowledge_base.catalog import BookCatalogEntry, list_book_catalog, search_book_catalog


def _write_metadata_sidecar(docs_root, records) -> None:
    sidecar = docs_root / ".book_metadata.jsonl"
    sidecar.write_text(
        "\n".join(records) + "\n",
        encoding="utf-8",
    )


def test_search_book_catalog_uses_layered_metadata_for_specific_query(tmp_path, monkeypatch) -> None:
    docs_root = tmp_path / "knowledge" / "docs"
    docs_root.mkdir(parents=True)
    (docs_root / "general_history.md").write_text("# 总论\n中国历史概述", encoding="utf-8")
    (docs_root / "finance_history.md").write_text("# 财政史\n财政制度演变", encoding="utf-8")
    _write_metadata_sidecar(
        docs_root,
        [
            '{"source_filename":"general_history.md","type":"core","categories":["通史"],"eras":["先秦-民国"],"summary":"中国历史通论"}',
            '{"source_filename":"finance_history.md","type":"specialized","categories":["财政史","税制"],"eras":["明清"],"summary":"财政制度演变"}',
        ],
    )

    monkeypatch.setattr(
        catalog_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(docs_path=str(docs_root)),
    )

    results = search_book_catalog("财政制度演变", top_k=2)

    assert [item.title for item in results][0] == "finance_history"
    assert results[0].type == "specialized"
    assert results[0].score is not None
    assert "财政史" in results[0].categories


def test_search_book_catalog_uses_layered_metadata_for_broad_query(tmp_path, monkeypatch) -> None:
    docs_root = tmp_path / "knowledge" / "docs"
    docs_root.mkdir(parents=True)
    (docs_root / "general_history.md").write_text("# 总论\n中国历史概述", encoding="utf-8")
    (docs_root / "finance_history.md").write_text("# 财政史\n财政制度演变", encoding="utf-8")
    _write_metadata_sidecar(
        docs_root,
        [
            '{"source_filename":"general_history.md","type":"core","categories":["通史"],"eras":["先秦-民国"],"summary":"中国历史通论"}',
            '{"source_filename":"finance_history.md","type":"specialized","categories":["财政史","税制"],"eras":["明清"],"summary":"财政制度演变"}',
        ],
    )

    monkeypatch.setattr(
        catalog_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(docs_path=str(docs_root)),
    )

    results = search_book_catalog("中国历史通史概述", top_k=2)

    assert [item.title for item in results][0] == "general_history"
    assert results[0].type == "core"
    assert results[0].score is not None


def test_search_book_catalog_reads_generated_sidecar_metadata(tmp_path, monkeypatch) -> None:
    docs_root = tmp_path / "knowledge" / "docs"
    docs_root.mkdir(parents=True)
    (docs_root / "finance_history.md").write_text("# 财政史\n财政制度演变", encoding="utf-8")
    record = build_book_metadata_record(
        source_filename="finance_history.md",
        source_title="finance_history",
        page_count=12,
        prompt_input={
            "source_filename": "finance_history.md",
            "title": "finance_history",
            "page_count": 12,
            "selected_pages": [],
            "selection_notes": [],
        },
        suggestion={
            "title": "finance_history",
            "type": {"value": "specialized", "confidence": 0.92, "evidence": "目录"},
            "categories": [{"value": "财政史", "confidence": 0.9, "evidence": "标题"}],
            "summary": {"value": "财政制度演变专题。", "confidence": 0.8, "evidence": "样本"},
        },
    )
    save_book_metadata(docs_root, "finance_history.md", record)

    monkeypatch.setattr(
        catalog_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(docs_path=str(docs_root)),
    )

    results = search_book_catalog("财政制度演变", top_k=1)

    assert results[0].type == "specialized"
    assert "财政史" in results[0].categories
    assert results[0].metadata_source is not None


def test_search_book_catalog_can_route_by_folder_path(tmp_path, monkeypatch) -> None:
    docs_root = tmp_path / "knowledge" / "docs"
    docs_root.mkdir(parents=True)
    (docs_root / "late_qing_finance.md").write_text("# 晚清财政\n厘金与关税", encoding="utf-8")
    record = build_book_metadata_record(
        source_filename="late_qing_finance.md",
        source_title="late_qing_finance",
        page_count=12,
        prompt_input={
            "source_filename": "late_qing_finance.md",
            "title": "late_qing_finance",
            "page_count": 12,
            "selected_pages": [],
            "selection_notes": [],
        },
        suggestion={
            "title": "晚清财政史料",
            "type": {"value": "specialized", "confidence": 0.92, "evidence": "目录"},
            "folder": {"value": "财政史/清代/晚清", "confidence": 0.91, "evidence": "目录"},
            "summary": {"value": "晚清厘金与关税专题。", "confidence": 0.8, "evidence": "样本"},
        },
    )
    save_book_metadata(docs_root, "late_qing_finance.md", record)

    monkeypatch.setattr(
        catalog_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(docs_path=str(docs_root)),
    )

    results = search_book_catalog("晚清 财政史 清代", top_k=1)

    assert results[0].folder_path == "财政史/清代/晚清"
    assert results[0].filename == "late_qing_finance.md"
    assert results[0].type == "specialized"


def test_search_book_catalog_folder_paths_hard_filter(tmp_path, monkeypatch) -> None:
    docs_root = tmp_path / "knowledge" / "docs"
    docs_root.mkdir(parents=True)
    (docs_root / "qing_finance.md").write_text("# 清代财政\n", encoding="utf-8")
    (docs_root / "song_finance.md").write_text("# 宋代财政\n", encoding="utf-8")
    save_book_metadata(
        docs_root,
        "qing_finance.md",
        build_book_metadata_record(
            source_filename="qing_finance.md",
            source_title="qing_finance",
            page_count=10,
            prompt_input={
                "source_filename": "qing_finance.md",
                "title": "qing_finance",
                "page_count": 10,
                "selected_pages": [],
                "selection_notes": [],
            },
            suggestion={
                "folder": {"value": "财政史/清代", "confidence": 0.9, "evidence": "目录"},
                "type": {"value": "specialized", "confidence": 0.9, "evidence": "目录"},
            },
        ),
    )
    save_book_metadata(
        docs_root,
        "song_finance.md",
        build_book_metadata_record(
            source_filename="song_finance.md",
            source_title="song_finance",
            page_count=10,
            prompt_input={
                "source_filename": "song_finance.md",
                "title": "song_finance",
                "page_count": 10,
                "selected_pages": [],
                "selection_notes": [],
            },
            suggestion={
                "folder": {"value": "财政史/宋代", "confidence": 0.9, "evidence": "目录"},
                "type": {"value": "specialized", "confidence": 0.9, "evidence": "目录"},
            },
        ),
    )

    monkeypatch.setattr(
        catalog_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(docs_path=str(docs_root)),
    )

    results = search_book_catalog(
        "财政史",
        top_k=5,
        folder_paths=["财政史/清代"],
    )

    assert [item.filename for item in results] == ["qing_finance.md"]


def test_search_book_catalog_broad_query_keeps_core_and_specialized_books(tmp_path, monkeypatch) -> None:
    docs_root = tmp_path / "knowledge" / "docs"
    docs_root.mkdir(parents=True)
    (docs_root / "qing_general.md").write_text("# 清代财政总论\n清代财政总体变迁", encoding="utf-8")
    (docs_root / "qing_tax.md").write_text("# 清代税制\n田赋与厘金改革", encoding="utf-8")
    (docs_root / "qing_salt.md").write_text("# 清代盐政\n盐课与专卖财政", encoding="utf-8")
    _write_metadata_sidecar(
        docs_root,
        [
            '{"source_filename":"qing_general.md","type":"core","categories":["财政史","清史"],"eras":["清代"],"summary":"清代财政通论"}',
            '{"source_filename":"qing_tax.md","type":"specialized","categories":["税制","财政史"],"eras":["清代"],"summary":"清代税制演变"}',
            '{"source_filename":"qing_salt.md","type":"reference","categories":["盐政","财政史"],"eras":["清代"],"summary":"清代盐课资料"}',
        ],
    )

    monkeypatch.setattr(
        catalog_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(docs_path=str(docs_root)),
    )

    results = search_book_catalog("清代中国财政情况变迁", top_k=3)

    result_types = {item.type for item in results}
    assert "core" in result_types
    assert "specialized" in result_types or "reference" in result_types
    assert len(results) >= 3


def test_list_book_catalog_reads_global_ingestion_preview_filename(tmp_path, monkeypatch) -> None:
    docs_root = tmp_path / "knowledge" / "docs"
    ingestion_dir = docs_root / ".ingestion"
    docs_root.mkdir(parents=True)
    ingestion_dir.mkdir(parents=True)
    (docs_root / "finance_history.preview.md").write_text("# 财政史\n财政制度演变", encoding="utf-8")
    (ingestion_dir / "finance_history.pdf.json").write_text(
        """
        {
          "source_filename": "finance_history.pdf",
          "preview_filename": "finance_history.preview.md",
          "display_title": "finance_history",
          "indexable": true,
          "preview_artifact_url": "/api/knowledge/docs/finance_history.preview.md"
        }
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        catalog_module,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(docs_path=str(docs_root)),
    )

    entries = list_book_catalog()

    assert len(entries) == 1
    assert entries[0].filename == "finance_history.pdf"
    assert entries[0].source_path.endswith("finance_history.preview.md")
    assert entries[0].preview.startswith("# 财政史")


def test_book_search_tool_groups_candidates_by_layer(monkeypatch) -> None:
    candidates = [
        BookCatalogEntry(
            doc_id="user-1",
            title="User Book",
            filename="user.md",
            scope="user",
            source_path="/tmp/user.md",
            source_url="/api/secure-knowledge/users/me/knowledge/docs/user.md",
            original_url=None,
            preview="",
            search_text="user",
            search_tokens=["user"],
            type="user",
            categories=["摘录"],
            eras=["民国"],
            regions=["全国"],
            keywords=[],
            summary="用户材料",
            priority=0,
            score=5.0,
        ),
        BookCatalogEntry(
            doc_id="core-1",
            title="Core Book",
            filename="core.md",
            scope="global",
            source_path="/tmp/core.md",
            source_url="/api/knowledge/docs/core.md",
            original_url=None,
            preview="",
            search_text="core",
            search_tokens=["core"],
            type="core",
            categories=["通史"],
            eras=["明清"],
            regions=["全国"],
            keywords=[],
            summary="核心通史",
            priority=1,
            score=4.0,
        ),
        BookCatalogEntry(
            doc_id="spec-1",
            title="Spec Book",
            filename="spec.md",
            scope="global",
            source_path="/tmp/spec.md",
            source_url="/api/knowledge/docs/spec.md",
            original_url=None,
            preview="",
            search_text="spec",
            search_tokens=["spec"],
            type="specialized",
            categories=["财政史"],
            eras=["明清"],
            regions=["全国"],
            keywords=[],
            summary="专题支撑",
            priority=2,
            score=3.0,
        ),
        BookCatalogEntry(
            doc_id="ref-1",
            title="Ref Book",
            filename="ref.md",
            scope="global",
            source_path="/tmp/ref.md",
            source_url="/api/knowledge/docs/ref.md",
            original_url=None,
            preview="",
            search_text="ref",
            search_tokens=["ref"],
            type="reference",
            categories=["工具书"],
            eras=[],
            regions=[],
            keywords=[],
            summary="参考资料",
            priority=3,
            score=2.0,
        ),
    ]
    monkeypatch.setattr(
        tools_module,
        "search_book_catalog",
        lambda query, thread_id=None, user_id=None, top_k=8, doc_ids=None, scopes=None, folder_paths=None: candidates,
    )

    output = tools_module.book_search_tool.func(SimpleNamespace(context={}), "任意问题")

    assert "### 用户书籍" in output
    assert "### 核心通用书" in output
    assert "### 专题支撑书" in output
    assert "### 补充材料 / 参考工具书" in output
    assert "- User Book | doc_id=user-1 | 相关度=5.00" in output
    assert "user doc_ids: user-1" in output
    assert "core doc_ids: core-1" in output
    assert "specialized doc_ids: spec-1" in output
    assert "reference doc_ids: ref-1" in output
    assert "一次只批量检索一个层级的书目" in output
    assert "同层内可多本一起传给 `knowledge_search`" in output
    assert "默认顺序：用户书籍 -> 当前线程书籍 -> 核心通用书 -> 专题支撑书 -> 补充材料" in output


def test_book_search_tool_does_not_rebuild_directory_tree(monkeypatch) -> None:
    monkeypatch.setattr(
        tools_module,
        "search_book_catalog",
        lambda query, thread_id=None, user_id=None, top_k=8, doc_ids=None, scopes=None, folder_paths=None: [],
    )
    monkeypatch.setattr(
        tools_module,
        "list_book_catalog",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("book_search_tool should not list the catalog")),
    )

    output = tools_module.book_search_tool.func(SimpleNamespace(context={}), "任意问题")

    assert output == "No likely books found for this query."


def test_book_search_tool_uses_larger_top_k(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_search(query, thread_id=None, user_id=None, top_k=8, doc_ids=None, scopes=None, folder_paths=None):
        captured["top_k"] = top_k
        return []

    monkeypatch.setattr(tools_module, "search_book_catalog", fake_search)

    tools_module.book_search_tool.func(SimpleNamespace(context={}), "任意问题")

    assert captured["top_k"] == 20


def test_search_book_catalog_can_reuse_prelisted_entries(monkeypatch) -> None:
    entries = [
        BookCatalogEntry(
            doc_id="core-1",
            title="Core Book",
            filename="core.md",
            scope="global",
            source_path="/tmp/core.md",
            source_url="/api/knowledge/docs/core.md",
            original_url=None,
            preview="",
            search_text="财政制度演变 通史",
            search_tokens=["财政制度演变", "通史"],
            type="core",
        )
    ]

    monkeypatch.setattr(
        catalog_module,
        "list_book_catalog",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("search_book_catalog should reuse provided entries")),
    )

    results = search_book_catalog("财政制度演变", top_k=1, entries=entries)

    assert [item.doc_id for item in results] == ["core-1"]


def test_knowledge_search_tool_aligns_scopes_with_doc_ids(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _DummyRetriever:
        def search(self, query, thread_id=None, user_id=None, doc_ids=None, scopes=None, folder_paths=None):
            captured["query"] = query
            captured["thread_id"] = thread_id
            captured["user_id"] = user_id
            captured["doc_ids"] = doc_ids
            captured["scopes"] = scopes
            captured["folder_paths"] = folder_paths
            return []

    retriever_stub = ModuleType("src.community.knowledge_base.retriever")
    retriever_stub.get_retriever = lambda: _DummyRetriever()
    monkeypatch.setitem(sys.modules, "src.community.knowledge_base.retriever", retriever_stub)
    monkeypatch.setattr(
        tools_module,
        "list_book_catalog",
        lambda thread_id=None, user_id=None: [
            BookCatalogEntry(
                doc_id="global-doc",
                title="Global Book 1",
                filename="global-1.md",
                scope="global",
                source_path="/tmp/global-1.md",
                source_url="/api/knowledge/docs/global-1.md",
                original_url=None,
                preview="",
                search_text="global",
                search_tokens=["global"],
            ),
            BookCatalogEntry(
                doc_id="global-doc-2",
                title="Global Book 2",
                filename="global-2.md",
                scope="global",
                source_path="/tmp/global-2.md",
                source_url="/api/knowledge/docs/global-2.md",
                original_url=None,
                preview="",
                search_text="global",
                search_tokens=["global"],
            ),
        ],
    )

    tools_module.knowledge_search_tool.func(
        SimpleNamespace(context={"thread_id": "thread-1", "user_id": "user-1"}),
        "民国时期财政情况",
        doc_ids="global-doc,global-doc-2",
        scopes="global",
    )

    assert captured["doc_ids"] == ["global-doc", "global-doc-2"]
    assert captured["scopes"] == ["global"]


def test_knowledge_search_tool_forwards_folder_paths(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _DummyRetriever:
        def search(self, query, thread_id=None, user_id=None, doc_ids=None, scopes=None, folder_paths=None):
            captured["folder_paths"] = folder_paths
            return []

    retriever_stub = ModuleType("src.community.knowledge_base.retriever")
    retriever_stub.get_retriever = lambda: _DummyRetriever()
    monkeypatch.setitem(sys.modules, "src.community.knowledge_base.retriever", retriever_stub)

    tools_module.knowledge_search_tool.func(
        SimpleNamespace(context={}),
        "晚清财政情况",
        folder_paths=["财政史/清代", "财政史/晚清"],
    )

    assert captured["folder_paths"] == ["财政史/清代", "财政史/晚清"]


def test_knowledge_search_tool_rejects_mixed_layer_doc_ids(monkeypatch) -> None:
    retriever_stub = ModuleType("src.community.knowledge_base.retriever")
    retriever_stub.get_retriever = lambda: SimpleNamespace(search=lambda *args, **kwargs: [])
    monkeypatch.setitem(sys.modules, "src.community.knowledge_base.retriever", retriever_stub)
    monkeypatch.setattr(
        tools_module,
        "list_book_catalog",
        lambda thread_id=None, user_id=None: [
            BookCatalogEntry(
                doc_id="user-doc",
                title="User Book",
                filename="user.md",
                scope="user",
                source_path="/tmp/user.md",
                source_url="/api/secure-knowledge/users/me/knowledge/docs/user.md",
                original_url=None,
                preview="",
                search_text="user",
                search_tokens=["user"],
                type="user",
            ),
            BookCatalogEntry(
                doc_id="reference-doc",
                title="Reference Book",
                filename="ref.md",
                scope="global",
                source_path="/tmp/ref.md",
                source_url="/api/knowledge/docs/ref.md",
                original_url=None,
                preview="",
                search_text="ref",
                search_tokens=["ref"],
                type="reference",
            ),
        ],
    )

    output = tools_module.knowledge_search_tool.func(
        SimpleNamespace(context={"thread_id": "thread-1", "user_id": "user-1"}),
        "任意问题",
        doc_ids="user-doc,reference-doc",
    )

    assert "Error: 当前 `doc_ids` 混入了不同层级的书目" in output
    assert "不能在同一轮 `knowledge_search` 里批量检索" in output
    assert "用户书籍: user-doc" in output
    assert "补充材料 / 参考工具书: reference-doc" in output


def test_knowledge_search_tool_footer_warns_scope_and_query_misuse(monkeypatch) -> None:
    class _DummyRetriever:
        def search(self, query, thread_id=None, user_id=None, doc_ids=None, scopes=None, folder_paths=None):
            return [
                {
                    "content": "民国财政以税收、公债与币制调整为主要线索。",
                    "score": 0.91,
                    "filename": "finance.md",
                    "metadata": {
                        "title": "财政史",
                        "doc_id": "global-doc",
                        "scope": "global",
                        "page_no": 12,
                        "pdf_page_no": 12,
                        "paragraph_no": 3,
                    },
                }
            ]

    retriever_stub = ModuleType("src.community.knowledge_base.retriever")
    retriever_stub.get_retriever = lambda: _DummyRetriever()
    monkeypatch.setitem(sys.modules, "src.community.knowledge_base.retriever", retriever_stub)
    monkeypatch.setattr(
        tools_module,
        "resolve_result_citation_context",
        lambda result, thread_id=None, user_id=None: {
            "source_url": "/api/knowledge/docs/finance.md",
            "citation_url": "/api/knowledge/docs/finance.md?citation=1",
            "citation_title": "财政史",
            "citation_page_no": 12,
            "citation_pdf_page_no": 12,
            "citation_paragraph_no": 3,
            "citation_page": None,
            "source_label": None,
            "source_scope": "global",
            "original_title": None,
        },
    )

    output = tools_module.knowledge_search_tool.func(
        SimpleNamespace(context={}),
        "民国时期财政情况",
        doc_ids="global-doc",
        scopes="global",
    )

    assert "不要随手改成更空泛的短词" in output
    assert "`scopes` 是硬过滤" in output
    assert "只有在你已经尝试了合理的换 query / 换书层 / `knowledge_locate` 展开后" in output


def test_knowledge_search_tool_no_result_guides_grounded_retries_before_web(monkeypatch) -> None:
    class _DummyRetriever:
        def search(self, query, thread_id=None, user_id=None, doc_ids=None, scopes=None, folder_paths=None):
            return []

    retriever_stub = ModuleType("src.community.knowledge_base.retriever")
    retriever_stub.get_retriever = lambda: _DummyRetriever()
    monkeypatch.setitem(sys.modules, "src.community.knowledge_base.retriever", retriever_stub)

    output = tools_module.knowledge_search_tool.func(
        SimpleNamespace(context={}),
        "清代末期财政情况",
        doc_ids="core-doc",
        scopes="global",
    )

    assert "不要因为这一轮空结果就直接换到别的书层" in output
    assert "不要立刻放弃当前资料范围" in output
    assert "句子型专业 query" in output
    assert "关键词堆砌" in output
    assert "`晚清财政情况如何`" in output
    assert "`晚清财政收入结构发生了哪些变化`" in output
    assert "只有在同一批最相关书里做过这些 grounded retries" in output
