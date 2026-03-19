"""Book-level catalog and lightweight retrieval for knowledge docs."""

import json
import math
from dataclasses import dataclass
from pathlib import Path

from src.community.knowledge_base.common import (
    derive_global_doc_id,
    derive_thread_doc_id,
    extract_title_from_text,
    normalize_search_text,
    resolve_project_path,
    tokenize_search_text,
)
from src.community.knowledge_base.ingestion import build_record_lookup, list_ingestion_records
from src.community.knowledge_base.structured_document import load_structured_document
from src.config.knowledge_base_config import get_knowledge_base_config
from src.config.paths import get_paths


@dataclass
class BookCatalogEntry:
    doc_id: str
    title: str
    filename: str
    scope: str
    source_path: str
    source_url: str
    original_url: str | None
    preview: str
    search_text: str
    search_tokens: list[str]


def _read_preview(path: Path, max_chars: int = 800) -> str:
    try:
        return path.read_text(encoding="utf-8")[:max_chars]
    except Exception:
        return ""


def _sample_search_excerpt(text: str, slice_size: int = 1200) -> str:
    text = text.strip()
    if not text:
        return ""
    if len(text) <= slice_size * 2:
        return text[: slice_size * 2]

    midpoint = len(text) // 2
    start_mid = max(0, midpoint - slice_size // 2)
    end_mid = min(len(text), start_mid + slice_size)
    parts = [
        text[:slice_size],
        text[start_mid:end_mid],
        text[-slice_size:],
    ]
    return "\n".join(part for part in parts if part)


def _read_structured_preview(path: Path, max_chars: int = 800) -> str:
    payload = load_structured_document(path)
    if not payload:
        return ""
    full_text = str(payload.get("full_text", ""))
    return full_text[:max_chars]


def _read_structured_search_excerpt(path: Path, max_chars: int = 3600) -> str:
    payload = load_structured_document(path)
    if not payload:
        return ""
    full_text = str(payload.get("full_text", ""))
    excerpt = _sample_search_excerpt(full_text, slice_size=max_chars // 3)
    return excerpt[:max_chars]


def _build_global_entries() -> list[BookCatalogEntry]:
    kb_config = get_knowledge_base_config()
    docs_root = resolve_project_path(kb_config.docs_path)
    if not docs_root.exists():
        return []

    entries: list[BookCatalogEntry] = []
    ingestion_dir = docs_root / ".ingestion"
    preview_filenames_to_skip: set[str] = set()

    if ingestion_dir.exists():
        for path in sorted(ingestion_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if payload.get("schema_version") == 1:
                continue

            preview_filename = payload.get("preview_filename")
            if preview_filename:
                preview_filenames_to_skip.add(str(preview_filename))

            source_filename = payload.get("source_filename")
            if not payload.get("indexable") or not source_filename:
                continue

            preview_path = docs_root / str(preview_filename or source_filename)
            preview = _read_preview(preview_path)
            search_excerpt = _read_preview(preview_path, max_chars=3600)
            if not preview and payload.get("structured_path"):
                preview = _read_structured_preview(Path(str(payload["structured_path"])))
            if not search_excerpt and payload.get("structured_path"):
                search_excerpt = _read_structured_search_excerpt(Path(str(payload["structured_path"])))
            title = payload.get("display_title") or Path(str(source_filename)).stem
            extracted_title = extract_title_from_text(preview, title)
            entries.append(
                BookCatalogEntry(
                    doc_id=derive_global_doc_id(docs_root, Path(str(source_filename))),
                    title=title,
                    filename=str(source_filename),
                    scope="global",
                    source_path=str(preview_path),
                    source_url=payload.get("preview_artifact_url") or f"/api/knowledge/docs/{preview_path.name}",
                    original_url=payload.get("source_artifact_url"),
                    preview=preview[:240],
                    search_text=normalize_search_text(f"{title} {extracted_title} {search_excerpt}"),
                    search_tokens=tokenize_search_text(f"{title} {extracted_title} {search_excerpt}"),
                )
            )

    for path in sorted(docs_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
            continue
        if "/.ingestion/" in str(path):
            continue
        if path.name in preview_filenames_to_skip:
            continue

        preview = _read_preview(path)
        search_excerpt = _read_preview(path, max_chars=3600)
        extracted_title = extract_title_from_text(preview, path.stem)
        title = path.stem
        doc_id = derive_global_doc_id(docs_root, path)
        search_text = normalize_search_text(f"{title} {extracted_title} {search_excerpt}")
        entries.append(
            BookCatalogEntry(
                doc_id=doc_id,
                title=title,
                filename=path.name,
                scope="global",
                source_path=str(path),
                source_url=f"/api/knowledge/docs/{path.name}",
                original_url=None,
                preview=preview[:240],
                search_text=search_text,
                search_tokens=tokenize_search_text(f"{title} {extracted_title} {search_excerpt}"),
            )
        )
    return entries


def _build_thread_entries(thread_id: str) -> list[BookCatalogEntry]:
    uploads_dir = get_paths().sandbox_uploads_dir(thread_id)
    if not uploads_dir.exists():
        return []

    entries: list[BookCatalogEntry] = []
    _, records_by_index_target = build_record_lookup(thread_id)
    seen_index_targets: set[str] = set()

    for record in list_ingestion_records(thread_id):
        target_filename = record.get("index_target_filename")
        preview_filename = record.get("preview_filename")
        if preview_filename:
            seen_index_targets.add(str(preview_filename))
        if not record.get("indexable") or not target_filename:
            continue
        preview_path = uploads_dir / str(preview_filename or record.get("source_filename") or target_filename)
        structured_path = Path(str(record.get("structured_path"))) if record.get("structured_path") else None
        if not preview_path.exists() and not structured_path:
            continue

        preview = _read_preview(preview_path) if preview_path.exists() else ""
        search_excerpt = _read_preview(preview_path, max_chars=3600) if preview_path.exists() else ""
        if not preview and structured_path:
            preview = _read_structured_preview(structured_path)
        if not search_excerpt and structured_path:
            search_excerpt = _read_structured_search_excerpt(structured_path)
        title = record.get("display_title") or Path(record.get("source_filename", target_filename)).stem
        extracted_title = extract_title_from_text(preview, title)
        original_url = None
        source_filename = record.get("source_filename")
        if source_filename and source_filename != target_filename:
            original_url = record.get("source_artifact_url")

        entries.append(
            BookCatalogEntry(
                doc_id=derive_thread_doc_id(Path(source_filename or target_filename)),
                title=title,
                filename=source_filename or target_filename,
                scope="thread",
                source_path=str(preview_path),
                source_url=record.get("preview_artifact_url") or f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{preview_path.name}",
                original_url=original_url,
                preview=preview[:240],
                search_text=normalize_search_text(f"{title} {extracted_title} {search_excerpt}"),
                search_tokens=tokenize_search_text(f"{title} {extracted_title} {search_excerpt}"),
            )
        )

    for path in sorted(uploads_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
            continue
        if path.name in seen_index_targets or records_by_index_target.get(path.name):
            continue

        preview = _read_preview(path)
        search_excerpt = _read_preview(path, max_chars=3600)
        extracted_title = extract_title_from_text(preview, path.stem)
        title = path.stem

        entries.append(
            BookCatalogEntry(
                doc_id=derive_thread_doc_id(path),
                title=title,
                filename=path.name,
                scope="thread",
                source_path=str(path),
                source_url=f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{path.name}",
                original_url=None,
                preview=preview[:240],
                search_text=normalize_search_text(f"{title} {extracted_title} {search_excerpt}"),
                search_tokens=tokenize_search_text(f"{title} {extracted_title} {search_excerpt}"),
            )
        )
    return entries


def list_book_catalog(thread_id: str | None = None) -> list[BookCatalogEntry]:
    """List global knowledge books plus optional current-thread uploads."""
    entries = _build_global_entries()
    if thread_id:
        entries = _build_thread_entries(thread_id) + entries
    return entries


def _build_document_frequencies(entries: list[BookCatalogEntry]) -> dict[str, int]:
    frequencies: dict[str, int] = {}
    for entry in entries:
        for token in set(entry.search_tokens):
            frequencies[token] = frequencies.get(token, 0) + 1
    return frequencies


def _bm25_score(
    entry: BookCatalogEntry,
    *,
    query_tokens: list[str],
    doc_frequencies: dict[str, int],
    corpus_size: int,
    avg_doc_len: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    if not query_tokens:
        return 0.0

    score = 0.0
    token_counts: dict[str, int] = {}
    for token in entry.search_tokens:
        token_counts[token] = token_counts.get(token, 0) + 1

    doc_len = max(1, len(entry.search_tokens))
    for token in query_tokens:
        tf = token_counts.get(token, 0)
        if tf == 0:
            continue
        df = doc_frequencies.get(token, 0)
        idf = math.log(1 + (corpus_size - df + 0.5) / (df + 0.5))
        numerator = tf * (k1 + 1)
        denominator = tf + k1 * (1 - b + b * doc_len / max(avg_doc_len, 1.0))
        score += idf * numerator / denominator
    return score


def _exact_match_boost(entry: BookCatalogEntry, query: str, query_tokens: list[str]) -> float:
    boost = 0.0
    normalized_query = normalize_search_text(query)
    title_text = normalize_search_text(entry.title)
    filename_text = normalize_search_text(entry.filename)

    if normalized_query and normalized_query == title_text:
        boost += 12.0
    elif normalized_query and normalized_query in title_text:
        boost += 8.0

    if normalized_query and normalized_query in filename_text:
        boost += 6.0

    for token in query_tokens:
        if token in title_text:
            boost += 1.5
        if token in filename_text:
            boost += 1.25
    return boost


def search_book_catalog(query: str, thread_id: str | None = None, top_k: int = 8) -> list[BookCatalogEntry]:
    """Return the most relevant candidate books for a query."""
    entries = list_book_catalog(thread_id)
    tokens = tokenize_search_text(query)
    if not entries or not tokens:
        return []

    doc_frequencies = _build_document_frequencies(entries)
    avg_doc_len = sum(max(1, len(entry.search_tokens)) for entry in entries) / len(entries)
    scored: list[tuple[float, BookCatalogEntry]] = []
    for entry in entries:
        score = _bm25_score(
            entry,
            query_tokens=tokens,
            doc_frequencies=doc_frequencies,
            corpus_size=len(entries),
            avg_doc_len=avg_doc_len,
        )
        score += _exact_match_boost(entry, query, tokens)
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in scored[:top_k]]
