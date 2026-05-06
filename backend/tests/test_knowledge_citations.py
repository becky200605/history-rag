from types import SimpleNamespace

from src.community.knowledge_base.citations import KNOWLEDGE_CITATION_REGISTRY_KEY, resolve_result_citation_context
from src.community.knowledge_base.tools import _build_citation


def test_user_note_citation_prefers_user_document_and_current_location(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.community.knowledge_base.citations.locate_document",
        lambda **kwargs: SimpleNamespace(
            source_url="/api/knowledge/docs/original-book.pdf",
            title="原书",
        ),
    )

    result = {
        "filename": "my-note.md",
        "source_type": "structured",
        "page": None,
        "metadata": {
            "scope": "user",
            "source_kind": "excerpt",
            "title": "我的摘录",
            "filename": "my-note.md",
            "page_no": 1,
            "pdf_page_no": 1,
            "paragraph_no": 3,
            "origin_scope": "global",
            "origin_filename": "original-book.pdf",
            "origin_anchor": {
                "page_no": 88,
                "pdf_page_no": 90,
                "paragraph_no": 2,
            },
        },
    }

    context = resolve_result_citation_context(
        result,
        thread_id="thread-1",
        user_id="user-1",
    )

    assert context["citation_title"] == "你的笔记：我的摘录"
    assert context["citation_page_no"] == 1
    assert context["citation_pdf_page_no"] == 1
    assert context["citation_paragraph_no"] == 3
    assert context["source_label"] == "你的笔记"
    assert context["citation_url"].startswith(
        "/api/secure-knowledge/users/me/knowledge/docs/my-note.md?"
    )
    assert "citation_source_label=%E4%BD%A0%E7%9A%84%E7%AC%94%E8%AE%B0" in context["citation_url"]
    assert "citation_origin_title=%E5%8E%9F%E4%B9%A6" in context["citation_url"]


def test_user_upload_citation_uses_uploaded_document_url(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.community.knowledge_base.citations.locate_document",
        lambda **kwargs: None,
    )

    result = {
        "filename": "user-upload.pdf",
        "source_type": "pdf",
        "page": 4,
        "metadata": {
            "scope": "user",
            "source_kind": "upload",
            "title": "用户上传文档",
            "filename": "user-upload.pdf",
        },
    }

    context = resolve_result_citation_context(
        result,
        thread_id="thread-1",
        user_id="user-1",
    )

    assert context["citation_title"] == "你上传的文档：用户上传文档"
    assert context["source_label"] == "你上传的文档"
    assert context["citation_url"].startswith(
        "/api/secure-knowledge/users/me/knowledge/docs/user-upload.pdf?"
    )
    assert "page=4" in context["citation_url"]


def test_build_citation_requires_state_for_numbered_marker() -> None:
    citation = _build_citation(
        "民国财政史 (杨荫溥) 原书第10页第1段",
        "/api/knowledge/docs/%E6%B0%91%E5%9B%BD%E8%B4%A2%E6%94%BF%E5%8F%B2%20%28%E6%9D%A8%E8%8D%AB%E6%BA%A5%29.pdf?page_no=10&paragraph_no=1",
    )

    assert citation is None


def test_build_citation_registers_numbered_marker_when_state_is_available() -> None:
    state = {}
    citation = _build_citation(
        "民国财政史 (杨荫溥) 原书第10页第1段",
        "/api/knowledge/docs/book.pdf?page_no=10&paragraph_no=1",
        state=state,
    )

    assert citation == "[citation:1]"
    assert state[KNOWLEDGE_CITATION_REGISTRY_KEY] == [
        {
            "id": "1",
            "label": "民国财政史 (杨荫溥) 原书第10页第1段",
            "url": "/api/knowledge/docs/book.pdf?page_no=10&paragraph_no=1",
        }
    ]
