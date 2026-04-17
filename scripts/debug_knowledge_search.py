#!/usr/bin/env python3
"""Debug the knowledge_search pipeline with explicit doc_id diagnostics.

Examples:
    python3 scripts/debug_knowledge_search.py \
      --query "盛宣怀主持操办项目企业事业轮船招商局电报局铁路矿山" \
      --doc-ids "盛宣怀档案资料 第 5 卷 _可搜索.pdf, 盛宣怀档案资料  第 4 卷 _可搜索.pdf"

    python3 scripts/debug_knowledge_search.py \
      --payload-json '{"doc_ids":"a.pdf, b.pdf","query":"盛宣怀主持操办项目企业事业轮船招商局电报局铁路矿山"}'
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
from src.community.knowledge_base.common import normalize_search_text
from src.community.knowledge_base.tools import knowledge_search_tool
from src.config.knowledge_base_config import load_knowledge_base_config_from_dict


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Debug the knowledge_search tool.")
    parser.add_argument("--query", default=None, help="Query passed to knowledge_search.")
    parser.add_argument(
        "--doc-ids",
        default=None,
        help="Comma/Chinese-comma/semicolon/newline separated doc_ids string.",
    )
    parser.add_argument(
        "--knowledge-folders",
        default=None,
        help="Optional folder constraint, mainly for folder-only debug runs.",
    )
    parser.add_argument(
        "--scopes",
        default=None,
        help="Optional scopes, e.g. global or user,thread,global.",
    )
    parser.add_argument("--thread-id", default=None, help="Optional thread_id context.")
    parser.add_argument("--user-id", default=None, help="Optional user_id context.")
    parser.add_argument(
        "--payload-json",
        default=None,
        help="Optional JSON payload containing query/doc_ids/knowledge_folders/scopes.",
    )
    parser.add_argument(
        "--config",
        default=str(ROOT_DIR / "config.yaml"),
        help="Path to config.yaml.",
    )
    parser.add_argument(
        "--docs-path",
        default=None,
        help="Optional knowledge docs root override, e.g. /var/lib/history-rag/knowledge/docs.",
    )
    parser.add_argument(
        "--show-catalog-limit",
        type=int,
        default=20,
        help="How many catalog entries to show in the preview.",
    )
    parser.add_argument(
        "--list-doc-ids",
        action="store_true",
        help="Only list visible catalog doc_ids / filenames / titles, then exit.",
    )
    return parser.parse_args()


def _parse_loose_list(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    raw_items = [value] if isinstance(value, str) else list(value)
    parsed: list[str] = []
    for raw_item in raw_items:
        for candidate in re.split(r"[,，、;\n；]+", str(raw_item)):
            normalized = candidate.strip().strip("`\"'")
            if normalized:
                parsed.append(normalized)
    return parsed


def _parse_bracket_doc_ids(value: str | None) -> list[str]:
    if not value:
        return []
    stripped = value.strip()
    matches = re.findall(r"\[([^\[\]]+)\]", stripped)
    remainder = re.sub(r"\[[^\[\]]+\]", "", stripped).strip()
    if matches and not remainder:
        return [item.strip() for item in matches if item.strip()]
    return _parse_loose_list(value)


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.split()).strip()


def _load_env_files() -> None:
    load_dotenv(ROOT_DIR / ".env", override=False)
    load_dotenv(BACKEND_DIR / ".env", override=False)
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


def _load_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if args.payload_json:
        payload = json.loads(args.payload_json)

    query = payload.get("query") or args.query
    doc_ids = payload.get("doc_ids") or args.doc_ids
    knowledge_folders = payload.get("knowledge_folders") or args.knowledge_folders
    scopes = payload.get("scopes") or args.scopes

    if not query and not args.list_doc_ids:
        raise SystemExit("Missing query. Pass --query or --payload-json.")

    return {
        "query": query or "",
        "doc_ids": doc_ids,
        "knowledge_folders": knowledge_folders,
        "scopes": scopes,
    }


def _print_header(title: str) -> None:
    print(f"\n=== {title} ===")


def _describe_match(candidate: str, entries: list[BookCatalogEntry]) -> None:
    exact_doc_id = [entry for entry in entries if entry.doc_id == candidate]
    exact_filename = [entry for entry in entries if entry.filename == candidate]
    normalized_candidate = _normalize_whitespace(candidate)
    normalized_doc_id = [entry for entry in entries if _normalize_whitespace(entry.doc_id) == normalized_candidate]
    normalized_filename = [entry for entry in entries if _normalize_whitespace(entry.filename) == normalized_candidate]

    print(f"- input: {candidate!r}")
    print(f"  trimmed: {candidate.strip()!r}")
    print(f"  normalized_whitespace: {normalized_candidate!r}")
    print(f"  exact doc_id matches: {len(exact_doc_id)}")
    for entry in exact_doc_id[:3]:
        print(f"    -> doc_id={entry.doc_id!r} filename={entry.filename!r} scope={entry.scope}")
    print(f"  exact filename matches: {len(exact_filename)}")
    for entry in exact_filename[:3]:
        print(f"    -> doc_id={entry.doc_id!r} filename={entry.filename!r} scope={entry.scope}")
    print(f"  normalized doc_id matches: {len(normalized_doc_id)}")
    for entry in normalized_doc_id[:3]:
        print(f"    -> doc_id={entry.doc_id!r} filename={entry.filename!r} scope={entry.scope}")
    print(f"  normalized filename matches: {len(normalized_filename)}")
    for entry in normalized_filename[:3]:
        print(f"    -> doc_id={entry.doc_id!r} filename={entry.filename!r} scope={entry.scope}")


def main() -> int:
    args = _parse_args()
    _load_env_files()
    _load_knowledge_base_config(args.config, args.docs_path)
    payload = _load_payload(args)

    parsed_doc_ids = _parse_bracket_doc_ids(payload["doc_ids"])
    parsed_knowledge_folders = _parse_loose_list(payload["knowledge_folders"])

    started = perf_counter()
    entries = list_book_catalog(
        thread_id=args.thread_id,
        user_id=args.user_id,
        include_search_content=False,
        caller="scripts.debug_knowledge_search",
    )

    _print_header("INPUT")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    _print_header("PARSED DOC IDS")
    if not parsed_doc_ids:
        print("(none)")
    for item in parsed_doc_ids:
        print(repr(item))

    _print_header("TRIM / MATCH DIAGNOSTICS")
    if not parsed_doc_ids:
        print("(no doc_ids provided)")
    for item in parsed_doc_ids:
        _describe_match(item, entries)

    _print_header("CATALOG PREVIEW")
    print(f"catalog_entries={len(entries)} elapsed_ms={(perf_counter() - started) * 1000:.1f}")
    for entry in entries[: args.show_catalog_limit]:
        print(
            json.dumps(
                {
                    "doc_id": entry.doc_id,
                    "filename": entry.filename,
                    "title": entry.title,
                    "scope": entry.scope,
                    "folder_path": entry.folder_path,
                    "normalized_doc_id": normalize_search_text(entry.doc_id),
                    "normalized_filename": normalize_search_text(entry.filename),
                },
                ensure_ascii=False,
            )
        )

    if args.list_doc_ids:
        _print_header("VISIBLE DOC IDS")
        if not entries:
            print("(none)")
        for entry in entries:
            print(
                json.dumps(
                    {
                        "doc_id": entry.doc_id,
                        "filename": entry.filename,
                        "title": entry.title,
                        "scope": entry.scope,
                        "folder_path": entry.folder_path,
                    },
                    ensure_ascii=False,
                )
            )
        return 0

    runtime = SimpleNamespace(context={})
    if args.thread_id:
        runtime.context["thread_id"] = args.thread_id
    if args.user_id:
        runtime.context["user_id"] = args.user_id

    _print_header("KNOWLEDGE SEARCH OUTPUT")
    tool_started = perf_counter()
    output = knowledge_search_tool.func(
        runtime,
        query=payload["query"],
        doc_ids=payload["doc_ids"],
        scopes=payload["scopes"],
        knowledge_folders=parsed_knowledge_folders or None,
    )
    print(output)
    print(f"\nknowledge_search_elapsed_ms={(perf_counter() - tool_started) * 1000:.1f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
