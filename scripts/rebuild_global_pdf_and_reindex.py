#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.community.knowledge_base.document_parsers import build_structured_document_from_paddleocr
from src.community.knowledge_base.indexer import rebuild_global_knowledge_index
from src.community.knowledge_base.retriever import get_qdrant_client
from src.community.knowledge_base.structured_document import save_structured_document
from src.config.app_config import get_app_config
from src.gateway.routers.knowledge import (
    _build_global_ingestion_record,
    _load_global_record,
    _mark_global_record_parsed,
    _mark_global_records_indexed,
    _save_global_record,
    get_global_docs_dir,
    get_global_ingestion_dir,
)


def _clear_all_qdrant_collections() -> list[str]:
    client = get_qdrant_client()
    collections_response = client.get_collections()
    deleted: list[str] = []
    for collection in collections_response.collections:
        client.delete_collection(collection_name=collection.name)
        deleted.append(collection.name)
    return deleted


def _rebuild_single_global_pdf(filename: str) -> tuple[dict, Path]:
    docs_dir = get_global_docs_dir()
    ingestion_dir = get_global_ingestion_dir()
    source_path = docs_dir / filename
    if not source_path.exists():
        raise FileNotFoundError(f"Source PDF not found: {source_path}")

    record = _load_global_record(filename)
    if record is None:
        record = _build_global_ingestion_record(
            filename=filename,
            size=source_path.stat().st_size,
            content_type="application/pdf",
            hints={},
        )

    hints = dict(record.get("hints") or {})
    payload = build_structured_document_from_paddleocr(
        source_path,
        title=str(record.get("display_title") or source_path.stem),
        parser_name="paddleocr_pdf",
        hints=hints,
        language_hint=hints.get("language_hint"),
    )
    structured_path = save_structured_document(ingestion_dir, filename, payload)
    record["parse_method"] = "paddleocr_pdf"
    _mark_global_record_parsed(
        record,
        structured_filename=structured_path.name,
        structured_path=str(structured_path),
    )
    _save_global_record(filename, record)
    return record, structured_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild one global PDF structured document, clear local Qdrant, and reindex the global knowledge base.",
    )
    parser.add_argument("filename", help="Filename under knowledge/docs, for example: 民国财政史 (杨荫溥).pdf")
    parser.add_argument(
        "--skip-clear-qdrant",
        action="store_true",
        help="Skip deleting existing Qdrant collections before reindexing.",
    )
    args = parser.parse_args()

    get_app_config()

    record, structured_path = _rebuild_single_global_pdf(args.filename)
    print(f"Rebuilt structured document: {structured_path}")

    if not args.skip_clear_qdrant:
        deleted = _clear_all_qdrant_collections()
        print(f"Cleared Qdrant collections: {deleted or '[]'}")

    chunk_count = rebuild_global_knowledge_index()
    _mark_global_records_indexed()
    print(f"Rebuilt global knowledge index with {chunk_count} chunks")
    print(f"Updated record: {record.get('source_filename')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
