from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

from src.community.knowledge_base.locator import locate_document
from src.community.knowledge_base.user_store import build_user_doc_public_url


def encode_source_url(url: str | None) -> str | None:
    if not url:
        return url
    return quote(url, safe="/:?=&%#")


def append_pdf_page_fragment(url: str | None, pdf_page_no: int | None) -> str | None:
    if not url or not pdf_page_no or "#page=" in url:
        return url
    return f"{url}#page={pdf_page_no}"


def append_location_params(
    url: str | None,
    *,
    page: int | None = None,
    page_no: int | None = None,
    pdf_page_no: int | None = None,
    paragraph_no: int | None = None,
) -> str | None:
    if not url:
        return url
    base, sep, fragment = url.partition("#")
    params: dict[str, int] = {}
    if page is not None:
        params["page"] = page
    if page_no:
        params["page_no"] = page_no
    if pdf_page_no:
        params["pdf_page_no"] = pdf_page_no
    if paragraph_no:
        params["paragraph_no"] = paragraph_no
    if params:
        joiner = "&" if "?" in base else "?"
        base = f"{base}{joiner}{urlencode(params)}"
    if sep:
        return f"{base}#{fragment}"
    return base


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_thread_artifact_url(thread_id: str | None, filename: str | None) -> str | None:
    if not thread_id or not filename:
        return None
    return f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{filename}"


def _apply_result_location(
    url: str | None,
    *,
    source_type: str,
    page: int | None,
    page_no: int | None,
    pdf_page_no: int | None,
    paragraph_no: int | None,
) -> str | None:
    if source_type == "pdf" and page is not None and pdf_page_no is None:
        return append_location_params(url, page=page)
    url = append_pdf_page_fragment(url, pdf_page_no)
    return append_location_params(
        url,
        page_no=page_no,
        pdf_page_no=pdf_page_no,
        paragraph_no=paragraph_no,
    )


def _resolve_original_document(
    metadata: dict[str, Any],
    *,
    thread_id: str | None,
    user_id: str | None,
):
    origin_scope = str(metadata.get("origin_scope") or "").strip().lower()
    origin_doc_id = metadata.get("origin_doc_id")
    origin_filename = metadata.get("origin_filename")
    if origin_scope not in {"global", "thread", "user"}:
        return None
    if not origin_doc_id and not origin_filename:
        return None
    return locate_document(
        thread_id=thread_id if origin_scope == "thread" else None,
        user_id=user_id if origin_scope == "user" else None,
        doc_id=str(origin_doc_id) if origin_doc_id else None,
        filename=str(origin_filename) if origin_filename else None,
    )


def resolve_result_citation_context(
    result: dict[str, Any],
    *,
    thread_id: str | None,
    user_id: str | None,
) -> dict[str, Any]:
    metadata = result.get("metadata", {})
    filename = str(result.get("filename") or metadata.get("filename") or "")
    title = str(metadata.get("title") or filename or "Unknown")
    scope = str(metadata.get("scope") or "global")
    source_type = str(result.get("source_type", metadata.get("source_type", "unknown")) or "unknown")

    current_page = _coerce_int(result.get("page"))
    current_page_no = _coerce_int(metadata.get("page_no"))
    current_pdf_page_no = _coerce_int(metadata.get("pdf_page_no"))
    current_paragraph_no = _coerce_int(metadata.get("paragraph_no"))

    if scope == "thread":
        source_url = _build_thread_artifact_url(
            str(metadata.get("thread_id") or thread_id or ""),
            filename,
        )
    elif scope == "user":
        source_url = build_user_doc_public_url(filename) if filename else None
    else:
        source_url = f"/api/knowledge/docs/{filename}" if filename else None

    source_url = _apply_result_location(
        source_url,
        source_type=source_type,
        page=current_page,
        page_no=current_page_no,
        pdf_page_no=current_pdf_page_no,
        paragraph_no=current_paragraph_no,
    )

    original_document = _resolve_original_document(
        metadata,
        thread_id=thread_id,
        user_id=user_id,
    )
    origin_anchor = metadata.get("origin_anchor") if isinstance(metadata.get("origin_anchor"), dict) else {}
    citation_page_no = _coerce_int(origin_anchor.get("page_no")) or current_page_no
    citation_pdf_page_no = _coerce_int(origin_anchor.get("pdf_page_no")) or current_pdf_page_no
    citation_paragraph_no = _coerce_int(origin_anchor.get("paragraph_no")) or current_paragraph_no

    original_url: str | None = None
    original_title: str | None = None
    if original_document:
        original_url = original_document.source_url
        original_title = original_document.title
    elif scope == "thread":
        original_url = _build_thread_artifact_url(
            str(metadata.get("thread_id") or thread_id or ""),
            str(metadata.get("origin_filename") or filename or ""),
        )
    elif scope == "user":
        origin_scope = str(metadata.get("origin_scope") or "").strip().lower()
        origin_filename = str(metadata.get("origin_filename") or "")
        if origin_scope == "global" and origin_filename:
            original_url = f"/api/knowledge/docs/{origin_filename}"
        elif origin_scope == "thread":
            original_url = _build_thread_artifact_url(thread_id, origin_filename)
        elif origin_scope == "user" and origin_filename:
            original_url = build_user_doc_public_url(origin_filename)
    elif metadata.get("origin_filename"):
        original_url = f"/api/knowledge/docs/{metadata.get('origin_filename')}"

    original_url = _apply_result_location(
        original_url,
        source_type=source_type,
        page=current_page,
        page_no=citation_page_no,
        pdf_page_no=citation_pdf_page_no,
        paragraph_no=citation_paragraph_no,
    )

    return {
        "source_url": encode_source_url(source_url),
        "original_url": encode_source_url(original_url),
        "source_title": title,
        "original_title": original_title,
        "citation_title": original_title or title,
        "citation_page": current_page,
        "citation_page_no": citation_page_no,
        "citation_pdf_page_no": citation_pdf_page_no,
        "citation_paragraph_no": citation_paragraph_no,
        "source_scope": scope,
    }
