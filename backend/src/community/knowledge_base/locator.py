"""Structured document locator helpers for page/paragraph/line lookups."""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.community.knowledge_base.common import (
    derive_global_doc_id,
    derive_thread_doc_id,
    derive_user_doc_id,
    resolve_project_path,
)
from src.community.knowledge_base.ingestion import list_ingestion_records
from src.community.knowledge_base.structured_document import load_structured_document
from src.community.knowledge_base.user_store import build_user_doc_public_url, list_user_records
from src.config.knowledge_base_config import get_knowledge_base_config
from src.config.paths import get_paths


@dataclass
class LocatedDocument:
    doc_id: str
    title: str
    filename: str
    scope: str
    source_url: str
    original_url: str | None
    payload: dict[str, Any]


def _normalize_filename_for_match(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip()
    text = text.translate(str.maketrans({"　": " ", "\u00a0": " "}))
    return re.sub(r"\s+", "", text).lower()


def _filename_match_score(requested_filename: str | None, candidate_filename: str) -> float:
    requested = _normalize_filename_for_match(requested_filename)
    candidate = _normalize_filename_for_match(candidate_filename)
    if not requested or not candidate:
        return 0.0

    if requested == candidate:
        return 10_000.0

    requested_path = Path(requested)
    candidate_path = Path(candidate)
    requested_stem = requested_path.stem or requested
    candidate_stem = candidate_path.stem or candidate
    requested_suffix = requested_path.suffix
    candidate_suffix = candidate_path.suffix

    if requested_stem == candidate_stem:
        return 9_000.0 + (100.0 if requested_suffix == candidate_suffix else 0.0)

    score = 0.0
    if requested_suffix and candidate_suffix and requested_suffix == candidate_suffix:
        score += 15.0

    full_ratio = SequenceMatcher(None, requested, candidate).ratio()
    stem_ratio = SequenceMatcher(None, requested_stem, candidate_stem).ratio()
    score += max(full_ratio * 100.0, stem_ratio * 120.0)

    if requested_stem and candidate_stem:
        if requested_stem in candidate_stem or candidate_stem in requested_stem:
            score += 20.0

    return score


def _is_exact_identifier_match(
    *,
    requested_doc_id: str | None,
    requested_filename: str | None,
    candidate_doc_id: str,
    candidate_filename: str,
) -> bool:
    if requested_doc_id and requested_doc_id == candidate_doc_id:
        return True
    if requested_filename and requested_filename == candidate_filename:
        return True
    return False


def _locate_global_document(doc_id: str | None, filename: str | None) -> LocatedDocument | None:
    docs_root = resolve_project_path(get_knowledge_base_config().docs_path)
    ingestion_dir = docs_root / ".ingestion"
    best_match: tuple[float, LocatedDocument] | None = None

    if ingestion_dir.exists():
        for record_path in sorted(ingestion_dir.glob("*.json")):
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if record.get("schema_version") == 1:
                continue

            source_filename = str(record.get("source_filename") or "")
            if not source_filename:
                continue
            candidate_doc_id = derive_global_doc_id(docs_root, docs_root / source_filename)
            structured_path = record.get("structured_path")
            payload = load_structured_document(Path(str(structured_path))) if structured_path else None
            if not payload:
                continue

            document = LocatedDocument(
                doc_id=candidate_doc_id,
                title=str(payload.get("title") or record.get("display_title") or Path(source_filename).stem),
                filename=source_filename,
                scope="global",
                source_url=str(record.get("preview_artifact_url") or f"/api/knowledge/docs/{source_filename}"),
                original_url=record.get("source_artifact_url"),
                payload=payload,
            )

            if _is_exact_identifier_match(
                requested_doc_id=doc_id,
                requested_filename=filename,
                candidate_doc_id=candidate_doc_id,
                candidate_filename=source_filename,
            ):
                return document

            if filename:
                score = _filename_match_score(filename, source_filename)
                if score >= 70.0 and (best_match is None or score > best_match[0]):
                    best_match = (score, document)
    return best_match[1] if best_match else None


def _locate_thread_document(thread_id: str, doc_id: str | None, filename: str | None) -> LocatedDocument | None:
    uploads_dir = get_paths().sandbox_uploads_dir(thread_id)
    best_match: tuple[float, LocatedDocument] | None = None
    for record in list_ingestion_records(thread_id):
        source_filename = str(record.get("source_filename") or record.get("index_target_filename") or "")
        if not source_filename:
            continue
        candidate_doc_id = derive_thread_doc_id(Path(source_filename))
        structured_path = record.get("structured_path")
        payload = load_structured_document(Path(str(structured_path))) if structured_path else None
        if not payload:
            continue

        document = LocatedDocument(
            doc_id=candidate_doc_id,
            title=str(payload.get("title") or record.get("display_title") or Path(source_filename).stem),
            filename=source_filename,
            scope="thread",
            source_url=str(record.get("preview_artifact_url") or record.get("source_artifact_url") or ""),
            original_url=record.get("source_artifact_url"),
            payload=payload,
        )

        if _is_exact_identifier_match(
            requested_doc_id=doc_id,
            requested_filename=filename,
            candidate_doc_id=candidate_doc_id,
            candidate_filename=source_filename,
        ):
            return document

        if filename:
            score = _filename_match_score(filename, source_filename)
            if score >= 70.0 and (best_match is None or score > best_match[0]):
                best_match = (score, document)
    return best_match[1] if best_match else None


def _locate_user_document(user_id: str, doc_id: str | None, filename: str | None) -> LocatedDocument | None:
    docs_dir = get_paths().user_knowledge_docs_dir(user_id)
    best_match: tuple[float, LocatedDocument] | None = None
    for record in list_user_records(user_id):
        source_filename = str(record.get("source_filename") or record.get("index_target_filename") or "")
        record_id = str(record.get("id") or "")
        if not source_filename or not record_id:
            continue
        candidate_doc_id = derive_user_doc_id(record_id)
        structured_path = record.get("structured_path")
        payload = load_structured_document(Path(str(structured_path))) if structured_path else None
        if not payload:
            continue

        document = LocatedDocument(
            doc_id=candidate_doc_id,
            title=str(payload.get("title") or record.get("display_title") or Path(source_filename).stem),
            filename=source_filename,
            scope="user",
            source_url=build_user_doc_public_url(source_filename),
            original_url=build_user_doc_public_url(source_filename),
            payload=payload,
        )

        if _is_exact_identifier_match(
            requested_doc_id=doc_id,
            requested_filename=filename,
            candidate_doc_id=candidate_doc_id,
            candidate_filename=source_filename,
        ):
            return document

        if filename:
            score = _filename_match_score(filename, source_filename)
            if score >= 70.0 and (best_match is None or score > best_match[0]):
                best_match = (score, document)
    return best_match[1] if best_match else None


def locate_document(
    thread_id: str | None,
    user_id: str | None = None,
    doc_id: str | None = None,
    filename: str | None = None,
) -> LocatedDocument | None:
    """Resolve a structured document from a doc_id or filename."""
    if user_id:
        user_match = _locate_user_document(user_id, doc_id, filename)
        if user_match:
            return user_match
    if thread_id:
        thread_match = _locate_thread_document(thread_id, doc_id, filename)
        if thread_match:
            return thread_match
    return _locate_global_document(doc_id, filename)


def extract_document_context(
    *,
    payload: dict[str, Any],
    page_no: int | None = None,
    page_no_end: int | None = None,
    pdf_page_no: int | None = None,
    pdf_page_no_end: int | None = None,
    paragraph_no: int | None = None,
    line_start: int | None = None,
    line_end: int | None = None,
    window: int = 1,
) -> list[dict[str, Any]]:
    """Extract matching paragraphs plus optional nearby context."""
    if (
        page_no is None
        and page_no_end is None
        and pdf_page_no is None
        and pdf_page_no_end is None
        and paragraph_no is None
        and line_start is None
        and line_end is None
    ):
        raise ValueError(
            "At least one of page_no, page_no_end, pdf_page_no, pdf_page_no_end, paragraph_no, line_start, or line_end is required"
        )
    if page_no_end is not None and page_no is None:
        raise ValueError("page_no_end requires page_no")
    if pdf_page_no_end is not None and pdf_page_no is None:
        raise ValueError("pdf_page_no_end requires pdf_page_no")
    if page_no is not None and page_no_end is not None and page_no_end < page_no:
        raise ValueError("page_no_end must be greater than or equal to page_no")
    if pdf_page_no is not None and pdf_page_no_end is not None and pdf_page_no_end < pdf_page_no:
        raise ValueError("pdf_page_no_end must be greater than or equal to pdf_page_no")

    pages = payload.get("pages") or []
    selected: dict[tuple[int, int], dict[str, Any]] = {}
    for page in pages:
        current_page_no = int(page.get("page_no") or 0)
        current_pdf_page_no = int(page.get("pdf_page_no") or current_page_no)
        current_book_page_no = page.get("book_page_no")
        current_page_number_source = str(page.get("page_number_source") or "pdf")
        paragraphs = page.get("paragraphs") or []
        page_context = {
            "page_no": current_page_no,
            "pdf_page_no": current_pdf_page_no,
            "book_page_no": current_book_page_no,
            "page_number_source": current_page_number_source,
            "page_meta": page.get("meta") or {},
        }

        if page_no is not None and paragraph_no is None and line_start is None and line_end is None:
            page_no_upper = page_no_end if page_no_end is not None else page_no
            if page_no <= current_page_no <= page_no_upper:
                for para in paragraphs:
                    selected[(current_pdf_page_no, int(para.get("paragraph_no") or 0))] = {
                        **page_context,
                        **para,
                    }
                continue

        if pdf_page_no is not None and paragraph_no is None and line_start is None and line_end is None:
            pdf_page_upper = pdf_page_no_end if pdf_page_no_end is not None else pdf_page_no
            if pdf_page_no <= current_pdf_page_no <= pdf_page_upper:
                for para in paragraphs:
                    selected[(current_pdf_page_no, int(para.get("paragraph_no") or 0))] = {
                        **page_context,
                        **para,
                    }
                continue

        for index, para in enumerate(paragraphs):
            current_paragraph_no = int(para.get("paragraph_no") or 0)
            para_line_start = para.get("line_start")
            para_line_end = para.get("line_end")

            matches = True
            if page_no is not None:
                page_no_upper = page_no_end if page_no_end is not None else page_no
                if not (page_no <= current_page_no <= page_no_upper):
                    matches = False
            if pdf_page_no is not None:
                pdf_page_upper = pdf_page_no_end if pdf_page_no_end is not None else pdf_page_no
                if not (pdf_page_no <= current_pdf_page_no <= pdf_page_upper):
                    matches = False
            if paragraph_no is not None and current_paragraph_no != paragraph_no:
                matches = False
            if (line_start is not None or line_end is not None) and para_line_start is not None and para_line_end is not None:
                query_start = line_start if line_start is not None else para_line_start
                query_end = line_end if line_end is not None else para_line_end
                if para_line_end < query_start or para_line_start > query_end:
                    matches = False

            if not matches:
                continue

            left = max(0, index - window)
            right = min(len(paragraphs), index + window + 1)
            for nearby in paragraphs[left:right]:
                selected[(current_pdf_page_no, int(nearby.get("paragraph_no") or 0))] = {
                    **page_context,
                    **nearby,
                }

    return [selected[key] for key in sorted(selected.keys())]
