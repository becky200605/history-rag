#!/usr/bin/env python3
"""Debug the SQLite FTS keyword-search path end to end.

Examples:
    python3 scripts/debug_keyword_search.py \
      --query "張之洞 生平 官職 總督" \
      --doc-id "中國財政通史 第7卷上.pdf"

    python3 scripts/debug_keyword_search.py \
      --query "张之洞 洋务 实业 财政" \
      --doc-ids-json '["张之洞全集 6 公牍·咨札_12733699_可搜索.pdf"]'
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.community.knowledge_base.catalog import BookCatalogEntry, list_book_catalog
from src.community.knowledge_base.keyword_search_index import (
    _connect,
    _db_path,
    _ensure_schema,
    ensure_documents_indexed,
    resolve_documents_for_doc_ids,
    search_keyword_documents,
)
from src.community.knowledge_base.tools import knowledge_search_tool
from src.config.knowledge_base_config import get_knowledge_base_config, load_knowledge_base_config_from_dict


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Debug SQLite FTS keyword retrieval.")
    parser.add_argument("--query", default=None, help="Query passed to keyword search.")
    parser.add_argument(
        "--doc-id",
        action="append",
        default=[],
        help="Single doc_id. Can be provided multiple times.",
    )
    parser.add_argument(
        "--doc-ids",
        default=None,
        help="Comma/Chinese-comma/semicolon/newline separated doc_ids.",
    )
    parser.add_argument(
        "--doc-ids-json",
        default=None,
        help='Native JSON array string, for example \'["doc_a", "doc_b"]\'.',
    )
    parser.add_argument("--thread-id", default=None, help="Optional thread_id context.")
    parser.add_argument("--user-id", default=None, help="Optional user_id context.")
    parser.add_argument(
        "--payload-json",
        default=None,
        help="Optional JSON payload containing query/doc_ids/thread_id/user_id.",
    )
    parser.add_argument("--top-k", type=int, default=8, help="Keyword hit limit.")
    parser.add_argument(
        "--config",
        default=str(ROOT_DIR / "config.yaml"),
        help="Path to config.yaml.",
    )
    parser.add_argument(
        "--docs-path",
        default=None,
        help="Optional knowledge docs root override.",
    )
    parser.add_argument(
        "--show-catalog-limit",
        type=int,
        default=20,
        help="Catalog preview size.",
    )
    parser.add_argument(
        "--list-doc-ids",
        action="store_true",
        help="Only list visible catalog entries, then exit.",
    )
    parser.add_argument(
        "--skip-tool-output",
        action="store_true",
        help="Skip the final knowledge_search tool rendering block.",
    )
    return parser.parse_args()


def _load_env_files() -> None:
    load_dotenv(ROOT_DIR / ".env", override=False)
    load_dotenv(BACKEND_DIR / ".env", override=False)
    load_dotenv(BACKEND_DIR / ".production.env", override=False)
    load_dotenv(override=False)


def _resolve_value_leniently(value: Any) -> Any:
    if isinstance(value, str):
        if value.startswith("${") and value.endswith("}"):
            inner = value[2:-1]
            if ":-" in inner:
                env_name, default_value = inner.split(":-", 1)
                resolved = os.getenv(env_name)
                if resolved is not None:
                    return resolved
                if default_value in {"null", "None", "~"}:
                    return None
                return default_value
            return os.getenv(inner)
        if value.startswith("$") and len(value) > 1:
            return os.getenv(value[1:])
        return value
    if isinstance(value, dict):
        return {key: _resolve_value_leniently(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_value_leniently(item) for item in value]
    return value


def _load_knowledge_base_config(config_path: str, docs_path_override: str | None = None) -> None:
    with open(config_path, encoding="utf-8") as handle:
        raw_config = yaml.safe_load(handle) or {}
    knowledge_base_config = _resolve_value_leniently(raw_config.get("knowledge_base", {}))
    if isinstance(knowledge_base_config, dict) and docs_path_override:
        knowledge_base_config["docs_path"] = docs_path_override
    if isinstance(knowledge_base_config, dict):
        for optional_section in ("mineru", "translation_rpc"):
            section_value = knowledge_base_config.get(optional_section)
            if isinstance(section_value, dict) and any(value is None for value in section_value.values()):
                knowledge_base_config.pop(optional_section, None)
    load_knowledge_base_config_from_dict(knowledge_base_config)


def _parse_loose_list(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    raw_items = [value] if isinstance(value, str) else list(value)
    parsed: list[str] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        for candidate in re.split(r"[,，、;\n；]+", str(raw_item)):
            normalized = candidate.strip().strip("`\"'")
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            parsed.append(normalized)
    return parsed


def _parse_doc_ids(args: argparse.Namespace, payload: dict[str, Any]) -> list[str]:
    parsed: list[str] = []
    seen: set[str] = set()

    def add_many(values: list[str]) -> None:
        for value in values:
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            parsed.append(normalized)

    add_many(_parse_loose_list(payload.get("doc_ids")))
    add_many(_parse_loose_list(args.doc_id))
    add_many(_parse_loose_list(args.doc_ids))

    raw_json = payload.get("doc_ids_json") or args.doc_ids_json
    if raw_json:
        decoded = json.loads(str(raw_json))
        if not isinstance(decoded, list):
            raise SystemExit("--doc-ids-json must decode to a JSON array.")
        add_many([str(item) for item in decoded])

    return parsed


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.split()).strip()


def _format_language_hint(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    labels = {
        "zh-Hans": "简体中文",
        "zh-CN": "简体中文",
        "zh-Hant": "繁体中文",
        "zh-TW": "繁体中文",
        "zh-HK": "繁体中文",
        "en": "英文",
    }
    label = labels.get(normalized)
    return f"{label} ({normalized})" if label else normalized


def _load_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if args.payload_json:
        payload = json.loads(args.payload_json)
    query = payload.get("query") or args.query
    if not query and not args.list_doc_ids:
        raise SystemExit("Missing query. Pass --query or --payload-json.")
    return payload | {
        "query": query or "",
        "thread_id": payload.get("thread_id") or args.thread_id,
        "user_id": payload.get("user_id") or args.user_id,
    }


def _print_header(title: str) -> None:
    print(f"\n=== {title} ===")


def _describe_matches(candidate: str, entries: list[BookCatalogEntry]) -> None:
    exact_doc_id = [entry for entry in entries if entry.doc_id == candidate]
    exact_filename = [entry for entry in entries if entry.filename == candidate]
    normalized_candidate = _normalize_whitespace(candidate)
    normalized_doc_id = [entry for entry in entries if _normalize_whitespace(entry.doc_id) == normalized_candidate]
    normalized_filename = [
        entry for entry in entries if _normalize_whitespace(entry.filename) == normalized_candidate
    ]

    print(f"- input: {candidate!r}")
    print(f"  exact doc_id matches: {len(exact_doc_id)}")
    print(f"  exact filename matches: {len(exact_filename)}")
    print(f"  normalized doc_id matches: {len(normalized_doc_id)}")
    print(f"  normalized filename matches: {len(normalized_filename)}")


def _entry_lookup(entries: list[BookCatalogEntry]) -> dict[str, BookCatalogEntry]:
    mapping: dict[str, BookCatalogEntry] = {}
    for entry in entries:
        for key in {
            entry.doc_id,
            entry.filename,
            _normalize_whitespace(entry.doc_id),
            _normalize_whitespace(entry.filename),
        }:
            if key and key not in mapping:
                mapping[key] = entry
    return mapping


def _load_index_state_rows(documents: list[Any]) -> list[dict[str, Any]]:
    if not documents:
        return []

    connection = _connect()
    try:
        _ensure_schema(connection)
        rows: list[dict[str, Any]] = []
        for document in documents:
            state_row = connection.execute(
                """
                SELECT structured_path, structured_mtime_ns, structured_size, index_version, indexed_at
                FROM doc_index_state
                WHERE scope = ? AND owner_id = ? AND doc_id = ?
                """,
                (document.scope, document.owner_id, document.doc_id),
            ).fetchone()
            paragraph_count_row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM paragraph_fts
                WHERE scope = ? AND owner_id = ? AND doc_id = ?
                """,
                (document.scope, document.owner_id, document.doc_id),
            ).fetchone()
            rows.append(
                {
                    "scope": document.scope,
                    "owner_id": document.owner_id,
                    "doc_id": document.doc_id,
                    "structured_path": state_row["structured_path"] if state_row else str(document.structured_path),
                    "index_version": state_row["index_version"] if state_row else None,
                    "indexed_at": state_row["indexed_at"] if state_row else None,
                    "paragraph_count": paragraph_count_row["count"] if paragraph_count_row else 0,
                }
            )
        return rows
    finally:
        connection.close()


def main() -> int:
    args = _parse_args()
    _load_env_files()
    _load_knowledge_base_config(args.config, args.docs_path)
    payload = _load_payload(args)
    doc_ids = _parse_doc_ids(args, payload)
    config = get_knowledge_base_config()

    _print_header("RUNTIME CONFIG")
    print(
        json.dumps(
            {
                "docs_path": str(args.docs_path or config.docs_path),
                "sqlite_db_path": str(_db_path()),
                "query": payload["query"],
                "thread_id": payload.get("thread_id"),
                "user_id": payload.get("user_id"),
                "top_k": args.top_k,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    started = perf_counter()
    entries = list_book_catalog(
        thread_id=payload.get("thread_id"),
        user_id=payload.get("user_id"),
        include_search_content=False,
        caller="scripts.debug_keyword_search",
    )

    _print_header("CATALOG PREVIEW")
    print(f"catalog_entries={len(entries)} elapsed_ms={(perf_counter() - started) * 1000:.1f}")
    for entry in entries[: args.show_catalog_limit]:
        print(
            json.dumps(
                {
                    "doc_id": entry.doc_id,
                    "title": entry.title,
                    "filename": entry.filename,
                    "scope": entry.scope,
                    "folder_path": entry.folder_path,
                    "language_hint": entry.language_hint,
                },
                ensure_ascii=False,
            )
        )

    if args.list_doc_ids:
        _print_header("VISIBLE DOC IDS")
        for entry in entries:
            print(
                json.dumps(
                    {
                        "doc_id": entry.doc_id,
                        "title": entry.title,
                        "filename": entry.filename,
                        "scope": entry.scope,
                        "folder_path": entry.folder_path,
                        "language_hint": entry.language_hint,
                    },
                    ensure_ascii=False,
                )
            )
        return 0

    _print_header("PARSED DOC IDS")
    if not doc_ids:
        print("(none)")
    for doc_id in doc_ids:
        print(repr(doc_id))

    _print_header("DOC ID MATCH DIAGNOSTICS")
    if not doc_ids:
        print("(no doc_ids provided)")
    for doc_id in doc_ids:
        _describe_matches(doc_id, entries)

    entry_map = _entry_lookup(entries)
    selected_entries: list[BookCatalogEntry] = []
    seen_selected: set[str] = set()
    for doc_id in doc_ids:
        entry = entry_map.get(doc_id) or entry_map.get(_normalize_whitespace(doc_id))
        if entry is None or entry.doc_id in seen_selected:
            continue
        seen_selected.add(entry.doc_id)
        selected_entries.append(entry)

    _print_header("SELECTED BOOK METADATA")
    if not selected_entries:
        print("(no catalog entries matched the provided doc_ids)")
    for entry in selected_entries:
        print(
            json.dumps(
                {
                    "doc_id": entry.doc_id,
                    "title": entry.title,
                    "filename": entry.filename,
                    "scope": entry.scope,
                    "folder_path": entry.folder_path,
                    "language_hint": entry.language_hint,
                    "language_label": _format_language_hint(entry.language_hint),
                    "summary": entry.summary,
                },
                ensure_ascii=False,
            )
        )

    documents = resolve_documents_for_doc_ids(
        thread_id=payload.get("thread_id"),
        user_id=payload.get("user_id"),
        doc_ids=doc_ids,
    )
    resolved_doc_ids = {document.doc_id for document in documents}
    missing = [doc_id for doc_id in doc_ids if doc_id not in resolved_doc_ids]

    _print_header("RESOLVED INDEX DOCUMENTS")
    if not documents:
        print("(no documents resolved for indexing)")
    for document in documents:
        print(
            json.dumps(
                {
                    "doc_id": document.doc_id,
                    "title": document.title,
                    "filename": document.filename,
                    "scope": document.scope,
                    "owner_id": document.owner_id,
                    "structured_path": str(document.structured_path),
                },
                ensure_ascii=False,
            )
        )
    if missing:
        print(f"missing_doc_ids={json.dumps(missing, ensure_ascii=False)}")

    index_started = perf_counter()
    ensure_documents_indexed(documents)
    index_elapsed_ms = (perf_counter() - index_started) * 1000

    _print_header("SQLITE INDEX STATE")
    print(f"index_build_elapsed_ms={index_elapsed_ms:.1f}")
    print(f"sqlite_db_path={_db_path()}")
    index_rows = _load_index_state_rows(documents)
    if not index_rows:
        print("(no index rows)")
    for row in index_rows:
        print(json.dumps(row, ensure_ascii=False))

    _print_header("RAW KEYWORD HITS")
    search_started = perf_counter()
    raw_results = search_keyword_documents(
        payload["query"],
        thread_id=payload.get("thread_id"),
        user_id=payload.get("user_id"),
        doc_ids=doc_ids,
        top_k=args.top_k,
    )
    print(f"raw_keyword_elapsed_ms={(perf_counter() - search_started) * 1000:.1f}")
    if not raw_results:
        print("(no hits)")
    for index, result in enumerate(raw_results, 1):
        metadata = result.get("metadata", {})
        entry = entry_map.get(str(metadata.get("doc_id") or "")) if metadata.get("doc_id") else None
        print(f"\n--- hit {index} ---")
        print(
            json.dumps(
                {
                    "doc_id": metadata.get("doc_id"),
                    "title": metadata.get("title"),
                    "scope": metadata.get("scope"),
                    "page_no": metadata.get("page_no"),
                    "pdf_page_no": metadata.get("pdf_page_no"),
                    "paragraph_no": metadata.get("paragraph_no"),
                    "matched_keywords": result.get("matched_keywords"),
                    "score": result.get("score"),
                    "language_hint": entry.language_hint if entry else None,
                    "language_label": _format_language_hint(entry.language_hint) if entry else None,
                },
                ensure_ascii=False,
            )
        )
        print(result.get("content", ""))

    if args.skip_tool_output:
        return 0

    _print_header("KNOWLEDGE SEARCH TOOL OUTPUT")
    runtime = SimpleNamespace(context={})
    if payload.get("thread_id"):
        runtime.context["thread_id"] = payload["thread_id"]
    if payload.get("user_id"):
        runtime.context["user_id"] = payload["user_id"]
    tool_started = perf_counter()
    print(
        knowledge_search_tool.func(
            runtime,
            query=payload["query"],
            doc_ids=doc_ids,
        )
    )
    print(f"\nknowledge_search_elapsed_ms={(perf_counter() - tool_started) * 1000:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
