import mimetypes
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from src.community.knowledge_base.common import derive_global_doc_id, get_user_collection_name, resolve_project_path
from src.community.knowledge_base.document_parsers import (
    OFFICE_EXTENSIONS,
    PDF_EXTENSIONS,
    extract_office_text_with_markitdown,
)
from src.community.knowledge_base.indexer import (
    delete_user_knowledge_records,
    upsert_user_knowledge_records,
)
from src.community.knowledge_base.locator import extract_document_context, locate_document
from src.community.knowledge_base.mineru_grpc import build_structured_document_from_mineru_grpc
from src.community.knowledge_base.retriever import get_qdrant_client
from src.community.knowledge_base.structured_document import build_bbox_from_position, build_structured_document
from src.community.knowledge_base.translation_grpc import translate_blocks_to_chinese_via_grpc
from src.community.knowledge_base.user_store import (
    build_user_derived_record,
    build_user_doc_public_url,
    build_user_import_ref_record,
    build_user_upload_record,
    cleanup_user_record_artifacts,
    find_user_import_record,
    find_user_record_by_source_filename,
    get_user_docs_dir,
    list_user_records,
    load_user_record,
    mark_user_record_failed,
    mark_user_record_parsed,
    mark_user_records_indexed,
    persist_user_structured_document,
    persist_user_text_document,
    remove_user_record,
    save_user_record,
)
from src.config.knowledge_base_config import get_knowledge_base_config

router = APIRouter(prefix="/api/users/{user_id}/knowledge", tags=["knowledge-base"])

UPLOAD_CHUNK_SIZE = 1024 * 1024


class UserKnowledgeImportRequest(BaseModel):
    filename: str


class CreateUserDerivedKnowledgeRequest(BaseModel):
    title: str
    content: str
    source_kind: str
    origin_scope: str | None = None
    origin_doc_id: str | None = None
    origin_filename: str | None = None
    origin_anchor: dict[str, Any] | None = None
    derived_from_id: str | None = None
    hints: dict[str, str] | None = None


class UpdateUserKnowledgeContentRequest(BaseModel):
    title: str
    content: str = ""


class TranslationBlockRequest(BaseModel):
    key: str
    text: str


class TranslateBlocksRequest(BaseModel):
    paragraphs: list[TranslationBlockRequest]


async def save_upload_file(file: UploadFile, destination: Path, chunk_size: int = UPLOAD_CHUNK_SIZE) -> int:
    size = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as buffer:
        while chunk := await file.read(chunk_size):
            buffer.write(chunk)
            size += len(chunk)
    await file.close()
    return size


def _serialize_record(record: dict[str, Any]) -> dict[str, Any]:
    source_filename = record.get("source_filename")
    preview_filename = record.get("preview_filename")
    return {
        "id": record.get("id"),
        "user_id": record.get("user_id"),
        "source_kind": record.get("source_kind"),
        "title": record.get("title"),
        "display_title": record.get("display_title"),
        "origin_scope": record.get("origin_scope"),
        "origin_doc_id": record.get("origin_doc_id"),
        "origin_filename": record.get("origin_filename"),
        "origin_anchor": record.get("origin_anchor"),
        "retrieval_enabled": record.get("retrieval_enabled", False),
        "filename": source_filename,
        "size": record.get("source_size", 0),
        "extension": record.get("source_extension"),
        "content_type": record.get("content_type"),
        "parse_method": record.get("parse_method"),
        "parse_status": record.get("parse_status"),
        "indexable": record.get("indexable", False),
        "artifact_url": build_user_doc_public_url(str(source_filename)) if source_filename else None,
        "preview_filename": preview_filename,
        "preview_artifact_url": build_user_doc_public_url(str(preview_filename)) if preview_filename else None,
        "structured_filename": record.get("structured_filename"),
        "index_target_filename": record.get("index_target_filename"),
        "hints": record.get("hints", {}),
        "error": record.get("error"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


def _build_global_doc_id(filename: str) -> str:
    docs_root = resolve_project_path(get_knowledge_base_config().docs_path)
    return derive_global_doc_id(docs_root, docs_root / filename)


def _record_source_file_path(user_id: str, record: dict[str, Any]) -> Path | None:
    source_filename = record.get("source_filename")
    if not source_filename:
        return None
    return get_user_docs_dir(user_id) / str(source_filename)


def _read_record_text_content(user_id: str, record: dict[str, Any]) -> str | None:
    source_path = _record_source_file_path(user_id, record)
    if not source_path or not source_path.exists() or not source_path.is_file():
        return None
    try:
        return source_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return source_path.read_text(encoding="utf-8", errors="ignore")


def _format_origin_location(origin_anchor: dict[str, Any] | None) -> str | None:
    if not origin_anchor:
        return None

    location_parts: list[str] = []
    pdf_page_no = origin_anchor.get("pdf_page_no")
    page_no = origin_anchor.get("page_no")
    paragraph_no = origin_anchor.get("paragraph_no")

    if pdf_page_no:
        location_parts.append(f"PDF 第 {pdf_page_no} 页")
    elif page_no:
        location_parts.append(f"第 {page_no} 页")
    if paragraph_no:
        location_parts.append(f"第 {paragraph_no} 段")
    return " · ".join(location_parts) if location_parts else None


def _strip_markdown_quote_prefix(text: str) -> str:
    cleaned_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("> "):
            cleaned_lines.append(line[2:])
        elif line == ">":
            cleaned_lines.append("")
        elif line.startswith(">"):
            cleaned_lines.append(line[1:].lstrip())
        else:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip("\n")


def _extract_derived_sections(content: str) -> tuple[str | None, str, str]:
    normalized = content.replace("\r\n", "\n")
    lines = normalized.split("\n")
    title: str | None = None
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip() or None

    excerpt_heading_index = next(
        (index for index, line in enumerate(lines) if line.strip() == "## 原文摘录"),
        None,
    )
    editable_heading_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.strip() in {"## 我的摘抄笔记", "## 我的批注", "## 我的笔记", "## 我的内容"}
        ),
        None,
    )

    excerpt = ""
    if excerpt_heading_index is not None:
        excerpt_lines: list[str] = []
        for line in lines[excerpt_heading_index + 1 :]:
            if line.startswith("## "):
                break
            excerpt_lines.append(line)
        excerpt = _strip_markdown_quote_prefix("\n".join(excerpt_lines))

    editable_content = normalized.strip("\n")
    if editable_heading_index is not None:
        editable_content = "\n".join(lines[editable_heading_index + 1 :]).lstrip("\n")

    return title, excerpt, editable_content.rstrip("\n")


def _build_derived_markdown(
    *,
    title: str,
    source_kind: str,
    origin_filename: str | None,
    origin_anchor: dict[str, Any] | None,
    locked_excerpt: str,
    editable_content: str,
) -> str:
    location_label = _format_origin_location(origin_anchor)
    note_heading = "## 我的批注" if source_kind == "annotation" else "## 我的摘抄笔记"
    quote_block = locked_excerpt.strip("\n")
    quoted_excerpt = (
        "\n".join(f"> {line}" if line else ">" for line in quote_block.splitlines())
        if quote_block
        else "> "
    )
    parts = [
        f"# {title}",
        "",
        f"来源：{origin_filename or '未知来源'}",
        f"定位：{location_label}" if location_label else None,
        "",
        "## 原文摘录",
        "",
        quoted_excerpt,
        "",
        note_heading,
        "",
        editable_content.rstrip("\n"),
    ]
    return "\n".join(part for part in parts if part is not None).rstrip() + "\n"


def _record_is_text_editable(record: dict[str, Any]) -> bool:
    if record.get("source_kind") in {"excerpt", "annotation", "translation", "note"}:
        return True
    if record.get("source_kind") != "upload":
        return False
    source_filename = str(record.get("source_filename") or "")
    return Path(source_filename).suffix.lower() in {".md", ".txt"}


def _build_record_editor_payload(user_id: str, record: dict[str, Any]) -> dict[str, Any]:
    raw_content = _read_record_text_content(user_id, record)
    source_kind = str(record.get("source_kind") or "")
    title = str(record.get("display_title") or record.get("title") or "未命名资料")
    origin_anchor = record.get("origin_anchor") if isinstance(record.get("origin_anchor"), dict) else None

    mode = "readonly"
    editable = False
    editable_content = ""
    locked_excerpt = ""

    if source_kind in {"excerpt", "annotation", "translation", "note"}:
        parsed_title, parsed_excerpt, parsed_editable_content = _extract_derived_sections(raw_content or "")
        title = parsed_title or title
        locked_excerpt = str(origin_anchor.get("text") or parsed_excerpt or "").strip("\n") if origin_anchor else parsed_excerpt
        editable_content = parsed_editable_content
        mode = "derived"
        editable = True
    elif _record_is_text_editable(record):
        editable_content = raw_content or ""
        mode = "text"
        editable = True

    return {
        "record": _serialize_record(record),
        "title": title,
        "mode": mode,
        "editable": editable,
        "content": raw_content or "",
        "editable_content": editable_content,
        "locked_excerpt": locked_excerpt,
        "origin_filename": record.get("origin_filename"),
        "location_label": _format_origin_location(origin_anchor),
    }


def _cleanup_existing_upload(user_id: str, source_filename: str) -> None:
    existing = find_user_record_by_source_filename(user_id, source_filename)
    if existing:
        existing_record_id = existing.get("id")
        if existing_record_id:
            delete_user_knowledge_records(user_id, [str(existing_record_id)])
        cleanup_user_record_artifacts(existing)
        remove_user_record(user_id, str(existing["id"]))


def _structured_page_payload(document: Any, *, page_no: int | None, pdf_page_no: int | None) -> dict[str, Any] | None:
    for page in document.payload.get("pages") or []:
        current_page_no = int(page.get("page_no") or 0)
        current_pdf_page_no = int(page.get("pdf_page_no") or current_page_no)
        if page_no is not None and current_page_no != page_no:
            continue
        if pdf_page_no is not None and current_pdf_page_no != pdf_page_no:
            continue
        return {
            "doc_id": document.doc_id,
            "scope": document.scope,
            "filename": document.filename,
            "title": document.title,
            "page_count": len(list(document.payload.get("pages") or [])),
            "page_no": page.get("page_no"),
            "pdf_page_no": page.get("pdf_page_no"),
            "book_page_no": page.get("book_page_no"),
            "page_number_source": page.get("page_number_source"),
            "page_meta": page.get("meta") or {},
            "paragraphs": [
                {
                    **paragraph,
                    "bbox": paragraph.get("bbox") or build_bbox_from_position(paragraph.get("position")),
                }
                for paragraph in page.get("paragraphs") or []
            ],
            "source_url": build_user_doc_public_url(document.filename),
            "original_url": build_user_doc_public_url(document.filename),
        }
    return None


@router.get("/list", response_model=dict)
def list_user_knowledge_records(user_id: str) -> dict:
    records = list_user_records(user_id)
    indexed_count = sum(1 for record in records if record.get("parse_status") == "indexed")
    latest_updated_at = next(
        (record.get("updated_at") for record in records if record.get("updated_at")),
        None,
    )

    doc_count = 0
    try:
        config = get_knowledge_base_config()
        client = get_qdrant_client()
        collection = client.get_collection(get_user_collection_name(config.qdrant.collection_name, user_id))
        doc_count = collection.points_count or 0
    except Exception:
        doc_count = 0

    return {
        "records": [_serialize_record(record) for record in records],
        "count": len(records),
        "indexed_count": indexed_count,
        "doc_count": doc_count,
        "latest_updated_at": latest_updated_at,
    }


@router.post("/upload", response_model=dict)
async def upload_user_knowledge_files(
    user_id: str,
    files: list[UploadFile] = File(...),
    language_hint: str | None = Form(default=None),
    layout_hint: str | None = Form(default=None),
    document_type_hint: str | None = Form(default=None),
) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    docs_dir = get_user_docs_dir(user_id)
    uploaded: list[dict[str, Any]] = []
    indexed_record_ids: list[str] = []
    hints = {
        key: value
        for key, value in {
            "language_hint": language_hint,
            "layout_hint": layout_hint,
            "document_type_hint": document_type_hint,
        }.items()
        if value
    }

    for file in files:
        if not file.filename:
            continue

        safe_filename = Path(file.filename).name
        if not safe_filename:
            continue

        _cleanup_existing_upload(user_id, safe_filename)
        file_path = docs_dir / safe_filename
        file_size = await save_upload_file(file, file_path)
        record = build_user_upload_record(
            user_id=user_id,
            source_filename=safe_filename,
            size=file_size,
            content_type=file.content_type,
            hints=hints,
        )

        file_ext = file_path.suffix.lower()
        if file_ext in PDF_EXTENSIONS:
            record["parse_method"] = "ocr_pdf_mineru_grpc"
            try:
                structured_payload = build_structured_document_from_mineru_grpc(
                    file_path,
                    title=str(record["display_title"]),
                    parser_name=str(record["parse_method"]),
                    hints=hints,
                    language_hint=hints.get("language_hint"),
                )
            except Exception as exc:
                structured_payload = None
                record = mark_user_record_failed(record, f"MinerU gRPC failed: {exc}")
            if structured_payload:
                structured_filename = persist_user_structured_document(
                    user_id,
                    safe_filename,
                    structured_payload,
                )
                record = mark_user_record_parsed(
                    user_id,
                    record,
                    structured_filename=structured_filename,
                )
                indexed_record_ids.append(str(record["id"]))
        elif file_ext in OFFICE_EXTENSIONS:
            extracted_text = extract_office_text_with_markitdown(file_path)
            if extracted_text:
                structured_payload = build_structured_document(
                    source_filename=safe_filename,
                    title=str(record["display_title"]),
                    text=extracted_text,
                    parser_name=str(record["parse_method"]),
                    hints=hints,
                )
                structured_filename = persist_user_structured_document(
                    user_id,
                    safe_filename,
                    structured_payload,
                )
                record = mark_user_record_parsed(
                    user_id,
                    record,
                    structured_filename=structured_filename,
                )
                indexed_record_ids.append(str(record["id"]))
            else:
                record = mark_user_record_failed(record, "Office parser returned no text")
        elif file_ext in {".md", ".txt"}:
            structured_payload = build_structured_document(
                source_filename=safe_filename,
                title=str(record["display_title"]),
                text=file_path.read_text(encoding="utf-8"),
                parser_name=str(record["parse_method"]),
                hints=hints,
            )
            structured_filename = persist_user_structured_document(
                user_id,
                safe_filename,
                structured_payload,
            )
            record = mark_user_record_parsed(
                user_id,
                record,
                structured_filename=structured_filename,
                preview_filename=safe_filename,
            )
            indexed_record_ids.append(str(record["id"]))

        save_user_record(user_id, record)
        uploaded.append(_serialize_record(record))

    if indexed_record_ids:
        upsert_user_knowledge_records(user_id, indexed_record_ids)
        mark_user_records_indexed(user_id)

    return {
        "success": True,
        "records": uploaded,
        "message": f"Successfully uploaded {len(uploaded)} personal knowledge file(s)",
    }


@router.post("/import-from-global", response_model=dict)
def import_global_document_reference(user_id: str, payload: UserKnowledgeImportRequest) -> dict:
    filename = Path(payload.filename).name
    if not filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    docs_root = resolve_project_path(get_knowledge_base_config().docs_path)
    file_path = docs_root / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Global knowledge document not found")

    existing = find_user_import_record(user_id, filename)
    if existing:
        return {
            "success": True,
            "record": _serialize_record(existing),
            "message": f"{filename} is already in personal knowledge favorites",
        }

    record = build_user_import_ref_record(
        user_id=user_id,
        title=file_path.stem,
        origin_doc_id=_build_global_doc_id(filename),
        origin_filename=filename,
    )
    save_user_record(user_id, record)
    return {
        "success": True,
        "record": _serialize_record(record),
        "message": f"Added {filename} to personal knowledge favorites",
    }


@router.delete("/{record_id}", response_model=dict)
def delete_user_knowledge_record(user_id: str, record_id: str) -> dict:
    record = load_user_record(user_id, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Personal knowledge record not found")

    record_id_value = str(record.get("id") or record_id)
    cleanup_user_record_artifacts(record)
    remove_user_record(user_id, record_id)
    delete_user_knowledge_records(user_id, [record_id_value])
    mark_user_records_indexed(user_id)
    return {
        "success": True,
        "message": f"Deleted personal knowledge record {record_id}",
    }


@router.get("/{record_id}/content", response_model=dict)
def get_user_knowledge_record_content(user_id: str, record_id: str) -> dict:
    record = load_user_record(user_id, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Personal knowledge record not found")
    return _build_record_editor_payload(user_id, record)


@router.put("/{record_id}/content", response_model=dict)
def update_user_knowledge_record_content(
    user_id: str,
    record_id: str,
    payload: UpdateUserKnowledgeContentRequest,
) -> dict:
    record = load_user_record(user_id, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Personal knowledge record not found")
    if not _record_is_text_editable(record):
        raise HTTPException(status_code=400, detail="This record is not editable")

    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    editable_content = payload.content.replace("\r\n", "\n")
    source_filename = record.get("source_filename")
    if not source_filename:
        raise HTTPException(status_code=400, detail="Missing source filename")

    if record.get("source_kind") in {"excerpt", "annotation", "translation", "note"}:
        origin_anchor = record.get("origin_anchor") if isinstance(record.get("origin_anchor"), dict) else None
        existing_content = _read_record_text_content(user_id, record) or ""
        _, parsed_excerpt, _ = _extract_derived_sections(existing_content)
        locked_excerpt = str(origin_anchor.get("text") or parsed_excerpt or "").strip("\n") if origin_anchor else parsed_excerpt
        persisted_content = _build_derived_markdown(
            title=title,
            source_kind=str(record.get("source_kind") or ""),
            origin_filename=record.get("origin_filename"),
            origin_anchor=origin_anchor,
            locked_excerpt=locked_excerpt,
            editable_content=editable_content,
        )
    else:
        persisted_content = editable_content

    record["title"] = title
    record["display_title"] = title
    record["source_size"] = len(persisted_content.encode("utf-8"))

    persist_user_text_document(user_id, str(source_filename), persisted_content)
    structured_payload = build_structured_document(
        source_filename=str(source_filename),
        title=title,
        text=persisted_content,
        parser_name=str(record.get("parse_method") or "markdown"),
        hints=record.get("hints") or {},
    )
    structured_filename = persist_user_structured_document(
        user_id,
        str(source_filename),
        structured_payload,
    )
    record = mark_user_record_parsed(
        user_id,
        record,
        structured_filename=structured_filename,
        preview_filename=str(source_filename),
    )
    save_user_record(user_id, record)
    upsert_user_knowledge_records(user_id, [str(record.get("id") or record_id)])
    mark_user_records_indexed(user_id)

    latest = load_user_record(user_id, record_id) or record
    return _build_record_editor_payload(user_id, latest)


@router.post("/derived", response_model=dict)
def create_user_derived_knowledge_record(
    user_id: str,
    payload: CreateUserDerivedKnowledgeRequest,
) -> dict:
    source_kind = payload.source_kind.strip().lower()
    if source_kind not in {"excerpt", "annotation"}:
        raise HTTPException(status_code=400, detail="source_kind must be excerpt or annotation")

    title = payload.title.strip()
    content = payload.content.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    if not content:
        raise HTTPException(status_code=400, detail="content is required")

    temp_record = build_user_derived_record(
        user_id=user_id,
        source_kind=source_kind,
        title=title,
        source_filename="pending.md",
        size=0,
        origin_scope=payload.origin_scope,
        origin_doc_id=payload.origin_doc_id,
        origin_filename=payload.origin_filename,
        origin_anchor=payload.origin_anchor,
        derived_from_id=payload.derived_from_id,
        hints=payload.hints,
    )
    source_filename = f"{temp_record['id']}.md"
    encoded_content = content.encode("utf-8")
    record = build_user_derived_record(
        user_id=user_id,
        source_kind=source_kind,
        title=title,
        source_filename=source_filename,
        size=len(encoded_content),
        origin_scope=payload.origin_scope,
        origin_doc_id=payload.origin_doc_id,
        origin_filename=payload.origin_filename,
        origin_anchor=payload.origin_anchor,
        derived_from_id=payload.derived_from_id,
        hints=payload.hints,
    )
    record["id"] = temp_record["id"]
    record["created_at"] = temp_record["created_at"]
    record["updated_at"] = temp_record["updated_at"]

    persist_user_text_document(user_id, source_filename, content)
    structured_payload = build_structured_document(
        source_filename=source_filename,
        title=title,
        text=content,
        parser_name=str(record["parse_method"]),
        hints=payload.hints or {},
    )
    structured_filename = persist_user_structured_document(
        user_id,
        source_filename,
        structured_payload,
    )
    record = mark_user_record_parsed(
        user_id,
        record,
        structured_filename=structured_filename,
        preview_filename=source_filename,
    )
    save_user_record(user_id, record)
    upsert_user_knowledge_records(user_id, [str(record["id"])])
    mark_user_records_indexed(user_id)
    latest = load_user_record(user_id, str(record["id"])) or record
    return {
        "success": True,
        "record": _serialize_record(latest),
        "message": f"Created personal {source_kind} document",
    }


@router.get("/docs/{filename}", summary="Get a personal knowledge document by filename")
def get_user_knowledge_document(
    user_id: str,
    filename: str,
    download: bool = Query(default=False),
    page: int | None = Query(default=None),
):
    if "/" in filename or "\\" in filename or filename.startswith(".."):
        raise HTTPException(status_code=400, detail="Invalid filename")

    docs_dir = get_user_docs_dir(user_id)
    file_path = docs_dir / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Document not found")

    ext = file_path.suffix.lower()
    if download:
        media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return FileResponse(path=file_path, filename=filename, media_type=media_type)
    if ext == ".pdf":
        headers = {}
        if page is not None:
            headers["X-PDF-Page"] = str(page)
        return FileResponse(path=file_path, media_type="application/pdf", headers=headers)
    return FileResponse(path=file_path, media_type="text/markdown")


@router.get("/docs/{filename}/structured-page", response_model=dict)
def get_user_knowledge_structured_page(
    user_id: str,
    filename: str,
    page_no: int | None = Query(default=None),
    pdf_page_no: int | None = Query(default=None),
) -> dict:
    if page_no is None and pdf_page_no is None:
        raise HTTPException(status_code=400, detail="page_no or pdf_page_no is required")

    document = locate_document(thread_id=None, user_id=user_id, filename=filename)
    if not document:
        raise HTTPException(status_code=404, detail="Structured document not found")

    page_payload = _structured_page_payload(document, page_no=page_no, pdf_page_no=pdf_page_no)
    if page_payload is None:
        raise HTTPException(status_code=404, detail="Structured page not found")
    return page_payload


@router.post("/docs/{filename}/translate-blocks", response_model=dict)
def translate_user_knowledge_blocks(
    user_id: str,
    filename: str,
    payload: TranslateBlocksRequest,
) -> dict:
    document = locate_document(thread_id=None, user_id=user_id, filename=filename)
    if not document:
        raise HTTPException(status_code=404, detail="Structured document not found")

    blocks = [
        {
            "id": paragraph.key,
            "text": paragraph.text,
        }
        for paragraph in payload.paragraphs
        if paragraph.key.strip() and paragraph.text.strip()
    ]
    if not blocks:
        return {"translations": []}

    try:
        translations = translate_blocks_to_chinese_via_grpc(blocks)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Translation failed: {exc}") from exc

    return {
        "translations": [
            {
                "key": item["id"],
                "translation": item["translation"],
            }
            for item in translations
        ]
    }


@router.get("/docs/{filename}/paragraph-location", response_model=dict)
def get_user_knowledge_paragraph_location(
    user_id: str,
    filename: str,
    page_no: int | None = Query(default=None),
    pdf_page_no: int | None = Query(default=None),
    paragraph_no: int | None = Query(default=None),
) -> dict:
    if page_no is None and pdf_page_no is None and paragraph_no is None:
        raise HTTPException(status_code=400, detail="At least one of page_no, pdf_page_no, or paragraph_no is required")

    document = locate_document(thread_id=None, user_id=user_id, filename=filename)
    if not document:
        raise HTTPException(status_code=404, detail="Structured document not found")

    excerpts = extract_document_context(
        payload=document.payload,
        page_no=page_no,
        pdf_page_no=pdf_page_no,
        paragraph_no=paragraph_no,
        window=0,
    )
    if not excerpts:
        raise HTTPException(status_code=404, detail="Paragraph location not found")

    excerpt = excerpts[0]
    return {
        "doc_id": document.doc_id,
        "scope": document.scope,
        "filename": document.filename,
        "title": document.title,
        "page_count": len(list(document.payload.get("pages") or [])),
        "page_no": excerpt.get("page_no"),
        "pdf_page_no": excerpt.get("pdf_page_no"),
        "book_page_no": excerpt.get("book_page_no"),
        "paragraph_no": excerpt.get("paragraph_no"),
        "bbox": excerpt.get("bbox") or build_bbox_from_position(excerpt.get("position")),
        "page_meta": excerpt.get("page_meta"),
        "text": str(excerpt.get("text") or ""),
        "source_url": build_user_doc_public_url(document.filename),
        "original_url": build_user_doc_public_url(document.filename),
    }


@router.get("/docs/{filename}/page-image", summary="Render a personal knowledge PDF page image")
def get_user_knowledge_document_page_image(
    user_id: str,
    filename: str,
    pdf_page_no: int = Query(..., ge=1),
    dpi: int = Query(default=144, ge=72, le=300),
):
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = get_user_docs_dir(user_id) / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Document not found")
    if file_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Page images are only available for PDF documents")

    try:
        import fitz
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF rendering dependency unavailable: {exc}") from exc

    try:
        with fitz.open(file_path) as document:
            page_index = pdf_page_no - 1
            if page_index < 0 or page_index >= document.page_count:
                raise HTTPException(status_code=404, detail="PDF page not found")
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
            png_bytes = pixmap.tobytes("png")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to render PDF page: {exc}") from exc

    return Response(content=png_bytes, media_type="image/png")
