"""MinerU gRPC integration for PDF parsing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import grpc

from src.community.knowledge_base.mineru_proto import mineru_pb2, mineru_pb2_grpc
from src.community.knowledge_base.structured_document import (
    build_bbox,
    build_page_reference,
    build_structured_document,
)
from src.config.knowledge_base_config import MineruConfig, get_knowledge_base_config

MAX_GRPC_MESSAGE_BYTES = 64 * 1024 * 1024


def _get_mineru_config() -> MineruConfig:
    config = get_knowledge_base_config().mineru
    if config is None or not config.enabled:
        raise RuntimeError("MinerU gRPC is not configured or is disabled")
    return config


def _coerce_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _build_metadata(config: MineruConfig) -> list[tuple[str, str]]:
    if not config.api_token:
        return []
    return [("authorization", f"Bearer {config.api_token}")]


def _build_channel(config: MineruConfig) -> grpc.Channel:
    options = [
        ("grpc.max_send_message_length", MAX_GRPC_MESSAGE_BYTES),
        ("grpc.max_receive_message_length", MAX_GRPC_MESSAGE_BYTES),
    ]
    if config.use_tls:
        credentials = grpc.ssl_channel_credentials()
        return grpc.secure_channel(config.target, credentials, options=options)
    return grpc.insecure_channel(config.target, options=options)


def _bbox_to_payload(bbox: mineru_pb2.BBox | None) -> dict[str, float] | None:
    if bbox is None:
        return None
    if bbox.width <= 0 or bbox.height <= 0:
        return None
    return build_bbox(x=bbox.x, y=bbox.y, width=bbox.width, height=bbox.height)


def _build_paragraphs_from_page_text(
    *,
    page_text: str,
    pdf_page_no: int,
    paragraph_no_in_doc_start: int,
    global_line_start: int,
) -> tuple[list[dict[str, Any]], int, int]:
    paragraphs: list[dict[str, Any]] = []
    paragraph_lines: list[str] = []
    paragraph_line_start: int | None = None
    paragraph_no_on_page = 1
    paragraph_no_in_doc = paragraph_no_in_doc_start
    global_line = global_line_start

    def flush_paragraph(current_line_no: int) -> None:
        nonlocal paragraph_no_on_page, paragraph_no_in_doc, paragraph_lines, paragraph_line_start
        if not paragraph_lines or paragraph_line_start is None:
            paragraph_lines = []
            paragraph_line_start = None
            return

        paragraph_text = "\n".join(paragraph_lines).strip()
        if paragraph_text:
            paragraphs.append(
                {
                    "paragraph_id": f"page-{pdf_page_no}-p{paragraph_no_on_page}",
                    "paragraph_no": paragraph_no_on_page,
                    "paragraph_no_in_doc": paragraph_no_in_doc,
                    "text": paragraph_text,
                    "line_start": paragraph_line_start,
                    "line_end": current_line_no,
                }
            )
            paragraph_no_on_page += 1
            paragraph_no_in_doc += 1

        paragraph_lines = []
        paragraph_line_start = None

    for line in page_text.splitlines():
        if line.strip():
            if paragraph_line_start is None:
                paragraph_line_start = global_line
            paragraph_lines.append(line)
        else:
            flush_paragraph(global_line - 1)
        global_line += 1

    flush_paragraph(global_line - 1)
    return paragraphs, paragraph_no_in_doc, global_line


def build_structured_document_from_mineru_response(
    *,
    source_filename: str,
    title: str,
    parser_name: str,
    response: mineru_pb2.ParsePdfResponse,
    hints: dict[str, str] | None = None,
) -> dict[str, Any]:
    hints = hints or {}

    if not response.document.pages and response.document.full_text.strip():
        payload = build_structured_document(
            source_filename=source_filename,
            title=title,
            text=response.document.full_text,
            parser_name=parser_name,
            hints=hints,
        )
        payload["provider"] = "mineru_grpc"
        if response.task_id:
            payload["provider_result_meta"] = {"task_id": response.task_id}
        return payload

    pages: list[dict[str, Any]] = []
    page_texts: list[str] = []
    paragraph_no_in_doc = 1
    global_line = 1

    for page_index, page in enumerate(response.document.pages, start=1):
        pdf_page_no = page.pdf_page_no or page.page_no or page_index
        page_reference = build_page_reference(pdf_page_no, hints)
        paragraphs: list[dict[str, Any]] = []
        page_text_parts: list[str] = []

        for paragraph_index, paragraph in enumerate(page.paragraphs, start=1):
            text = paragraph.text.strip()
            if not text:
                continue

            line_start = _coerce_positive_int(paragraph.line_start) or global_line
            line_end = _coerce_positive_int(paragraph.line_end)
            if line_end is None or line_end < line_start:
                line_end = line_start + max(1, text.count("\n") + 1) - 1

            bbox = _bbox_to_payload(paragraph.bbox if paragraph.HasField("bbox") else None)
            payload = {
                "paragraph_id": paragraph.paragraph_id or f"page-{pdf_page_no}-p{paragraph_index}",
                "paragraph_no": paragraph_index,
                "paragraph_no_in_doc": paragraph_no_in_doc,
                "text": text,
                "line_start": line_start,
                "line_end": line_end,
            }
            if bbox is not None:
                payload["bbox"] = bbox
                payload["bbox_source"] = paragraph.bbox_source or "mineru_grpc"

            paragraphs.append(payload)
            page_text_parts.append(text)
            paragraph_no_in_doc += 1
            global_line = line_end + 2

        page_text = page.text.strip() or "\n\n".join(page_text_parts).strip()
        if not paragraphs and page_text:
            paragraphs, paragraph_no_in_doc, global_line = _build_paragraphs_from_page_text(
                page_text=page_text,
                pdf_page_no=pdf_page_no,
                paragraph_no_in_doc_start=paragraph_no_in_doc,
                global_line_start=global_line,
            )

        meta = {}
        if page.page_width > 0:
            meta["page_width"] = page.page_width
        if page.page_height > 0:
            meta["page_height"] = page.page_height

        pages.append(
            {
                **page_reference,
                "text": page_text,
                "paragraphs": paragraphs,
                "meta": meta,
            }
        )
        page_texts.append(page_text)

    payload = {
        "schema_version": 1,
        "source_filename": source_filename,
        "title": title,
        "parser_name": parser_name,
        "hints": hints,
        "full_text": response.document.full_text.strip() or "\f".join(page_texts).strip(),
        "pages": pages,
        "provider": "mineru_grpc",
    }
    if response.task_id:
        payload["provider_result_meta"] = {"task_id": response.task_id}
    return payload


def build_structured_document_from_mineru_grpc(
    file_path: Path,
    *,
    title: str,
    parser_name: str,
    hints: dict[str, str] | None = None,
    language_hint: str | None = None,
) -> dict[str, Any]:
    config = _get_mineru_config()
    hints = hints or {}

    request = mineru_pb2.ParsePdfRequest(
        filename=file_path.name,
        file_content=file_path.read_bytes(),
        language_hint=language_hint or "",
        layout_hint=hints.get("layout_hint", ""),
        document_type_hint=hints.get("document_type_hint", ""),
        book_page_start_pdf_page=hints.get("book_page_start_pdf_page", ""),
        book_page_start_value=hints.get("book_page_start_value", ""),
        model_version=config.model_version,
    )

    try:
        with _build_channel(config) as channel:
            stub = mineru_pb2_grpc.MineruPdfExtractorStub(channel)
            response = stub.ParsePdf(
                request,
                timeout=config.request_timeout,
                metadata=_build_metadata(config),
            )
    except grpc.RpcError as exc:
        raise RuntimeError(f"MinerU gRPC failed: {exc.code().name} {exc.details()}") from exc

    return build_structured_document_from_mineru_response(
        source_filename=file_path.name,
        title=title,
        parser_name=parser_name,
        response=response,
        hints=hints,
    )
