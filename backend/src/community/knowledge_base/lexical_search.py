"""Lexical fallback retrieval for quote-like knowledge queries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from src.community.knowledge_base.common import (
    derive_global_doc_id,
    derive_thread_doc_id,
    derive_user_doc_id,
    normalize_search_text,
    resolve_project_path,
    tokenize_search_text,
)
from src.community.knowledge_base.ingestion import list_ingestion_records
from src.community.knowledge_base.structured_document import load_structured_document
from src.community.knowledge_base.user_store import list_user_records
from src.config.knowledge_base_config import get_knowledge_base_config
from src.config.paths import get_paths

def _iter_global_documents(doc_ids: set[str] | None = None) -> Iterator[dict[str, Any]]:
    docs_root = resolve_project_path(get_knowledge_base_config().docs_path)
    ingestion_dir = docs_root / ".ingestion"

    if ingestion_dir.exists():
        for record_path in sorted(ingestion_dir.glob("*.json")):
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if record.get("schema_version") == 1:
                continue

            source_filename = str(record.get("source_filename") or "")
            if not source_filename or not record.get("indexable"):
                continue
            doc_id = derive_global_doc_id(docs_root, docs_root / source_filename)
            if doc_ids and doc_id not in doc_ids:
                continue

            structured_path = Path(str(record.get("structured_path"))) if record.get("structured_path") else None
            payload = load_structured_document(structured_path) if structured_path else None
            if not payload:
                continue

            yield {
                "doc_id": doc_id,
                "title": str(payload.get("title") or record.get("display_title") or Path(source_filename).stem),
                "filename": source_filename,
                "scope": "global",
                "payload": payload,
                "source": str(record.get("structured_path") or record.get("source_path") or source_filename),
            }


def _iter_thread_documents(thread_id: str, doc_ids: set[str] | None = None) -> Iterator[dict[str, Any]]:
    uploads_dir = get_paths().sandbox_uploads_dir(thread_id)
    if not uploads_dir.exists():
        return

    for record in list_ingestion_records(thread_id):
        source_filename = str(record.get("source_filename") or record.get("index_target_filename") or "")
        if not source_filename or not record.get("indexable"):
            continue
        doc_id = derive_thread_doc_id(Path(source_filename))
        if doc_ids and doc_id not in doc_ids:
            continue

        structured_path = Path(str(record.get("structured_path"))) if record.get("structured_path") else None
        payload = load_structured_document(structured_path) if structured_path else None
        if not payload:
            continue

        yield {
            "doc_id": doc_id,
            "title": str(payload.get("title") or record.get("display_title") or Path(source_filename).stem),
            "filename": source_filename,
            "scope": "thread",
            "thread_id": thread_id,
            "payload": payload,
            "source": str(record.get("structured_path") or record.get("source_path") or source_filename),
        }


def _iter_user_documents(user_id: str, doc_ids: set[str] | None = None) -> Iterator[dict[str, Any]]:
    docs_dir = get_paths().user_knowledge_docs_dir(user_id)
    if not docs_dir.exists():
        return

    for record in list_user_records(user_id):
        if not record.get("retrieval_enabled") or not record.get("indexable"):
            continue
        source_filename = str(record.get("source_filename") or record.get("index_target_filename") or "")
        record_id = str(record.get("id") or "")
        if not source_filename or not record_id:
            continue
        doc_id = derive_user_doc_id(record_id)
        if doc_ids and doc_id not in doc_ids:
            continue

        structured_path = Path(str(record.get("structured_path"))) if record.get("structured_path") else None
        payload = load_structured_document(structured_path) if structured_path else None
        if not payload:
            continue

        yield {
            "doc_id": doc_id,
            "title": str(payload.get("title") or record.get("display_title") or Path(source_filename).stem),
            "filename": source_filename,
            "scope": "user",
            "user_id": user_id,
            "source_kind": str(record.get("source_kind") or "upload"),
            "origin_doc_id": record.get("origin_doc_id"),
            "payload": payload,
            "source": str(record.get("structured_path") or record.get("source_path") or source_filename),
        }


def _iter_candidate_documents(
    thread_id: str | None,
    user_id: str | None,
    doc_ids: list[str] | None = None,
    scopes: list[str] | None = None,
) -> Iterator[dict[str, Any]]:
    enabled_scopes = set(scopes or ["user", "thread", "global"])
    doc_id_set = set(doc_ids or []) or None
    if user_id and "user" in enabled_scopes:
        yield from _iter_user_documents(user_id, doc_ids=None)
    if thread_id and "thread" in enabled_scopes:
        yield from _iter_thread_documents(thread_id, doc_ids=None)
    if "global" in enabled_scopes:
        yield from _iter_global_documents(doc_ids=doc_id_set)


def _score_paragraph(
    query: str,
    paragraph_text: str,
) -> float:
    normalized_query = normalize_search_text(query)
    normalized_text = normalize_search_text(paragraph_text)
    if not normalized_text:
        return 0.0

    score = 0.0
    if normalized_query and len(normalized_query) >= 8 and normalized_query in normalized_text:
        score += 0.6

    query_tokens = set(tokenize_search_text(query))
    paragraph_tokens = set(tokenize_search_text(paragraph_text))
    if query_tokens and paragraph_tokens:
        overlap = query_tokens & paragraph_tokens
        if overlap:
            overlap_ratio = len(overlap) / max(len(query_tokens), 1)
            score += min(0.3, overlap_ratio * 0.3)

    return min(score, 0.99)


def lexical_search_documents(
    query: str,
    *,
    thread_id: str | None = None,
    user_id: str | None = None,
    doc_ids: list[str] | None = None,
    scopes: list[str] | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Scan structured documents lexically for quote-like or table-title queries."""
    results: list[dict[str, Any]] = []
    for document in _iter_candidate_documents(
        thread_id,
        user_id,
        doc_ids=doc_ids,
        scopes=scopes,
    ):
        payload = document.get("payload") or {}
        for page in payload.get("pages") or []:
            page_no = page.get("page_no")
            pdf_page_no = page.get("pdf_page_no") or page_no
            book_page_no = page.get("book_page_no")
            page_number_source = page.get("page_number_source")
            for paragraph in page.get("paragraphs") or []:
                content = str(paragraph.get("text") or "").strip()
                score = _score_paragraph(query, content)
                if score < 0.25:
                    continue
                metadata = {
                    "title": document["title"],
                    "doc_id": document["doc_id"],
                    "page_no": page_no,
                    "pdf_page_no": pdf_page_no,
                    "book_page_no": book_page_no,
                    "page_number_source": page_number_source,
                    "paragraph_no": paragraph.get("paragraph_no"),
                    "paragraph_no_in_doc": paragraph.get("paragraph_no_in_doc"),
                    "line_start": paragraph.get("line_start"),
                    "line_end": paragraph.get("line_end"),
                    "scope": document["scope"],
                    "filename": document["filename"],
                    "source": document["source"],
                }
                if document["scope"] == "thread":
                    metadata["thread_id"] = document.get("thread_id")
                    metadata["source_virtual_path"] = f"/mnt/user-data/uploads/{document['filename']}"
                    metadata["source_kind"] = "thread_upload"
                if document["scope"] == "user":
                    metadata["user_id"] = document.get("user_id")
                    metadata["source_kind"] = document.get("source_kind", "upload")
                    metadata["origin_doc_id"] = document.get("origin_doc_id")
                results.append(
                    {
                        "content": content,
                        "metadata": metadata,
                        "score": score,
                        "source": document["source"],
                        "filename": document["filename"],
                        "collection_name": "lexical_fallback",
                    }
                )

    results.sort(key=lambda item: item.get("score", 0), reverse=True)
    return results[:top_k]
