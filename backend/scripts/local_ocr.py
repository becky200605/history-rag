#!/usr/bin/env python3
"""
Run MinerU OCR locally on PDFs and produce server-ready ingestion records.

Workflow
--------
1. Run on your local machine (where MinerU gRPC is accessible):

       cd backend
       uv run python scripts/local_ocr.py /local/books/ \\
           --grpc-target 127.0.0.1:50051 \\
           --server-docs-dir /opt/app/knowledge/docs \\
           --concurrency 4

2. Copy results to the server:

       # Copy source PDFs (if not already there)
       rsync -av /local/books/*.pdf  user@server:/opt/app/knowledge/docs/

       # Copy ingestion records (includes structured JSON)
       rsync -av /local/books/.ingestion/  user@server:/opt/app/knowledge/docs/.ingestion/

The server will see parse_status="parsed" and skip OCR entirely.

Options
-------
--grpc-target       MinerU gRPC address (default: 127.0.0.1:50051)
--api-token         Bearer token for gRPC auth
--tls               Use TLS for gRPC connection
--model-version     MinerU model version (default: vlm)
--request-timeout   gRPC timeout in seconds (default: 14400)
--concurrency       Max parallel gRPC jobs (default: 4)
--disk-slots        Max concurrent disk reads/writes (default: 2)
--server-docs-dir   Absolute path to docs dir on the SERVER.
                    Embedded in ingestion records so the server finds files.
                    Defaults to the local input dir (ok for local-only testing).
--language-hint     Language hint passed to MinerU (e.g. "zh", "en")
--layout-hint       Layout hint passed to MinerU
--document-type-hint Document type hint
--skip-existing     Skip files that already have a parsed ingestion record (default: on)
--force             Re-process even if a parsed record already exists
--config            Path to config.yaml — reads [knowledge_base] section.
                    If also passing --grpc-target, the CLI value takes precedence.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

PDF_EXTENSIONS = {".pdf"}
OFFICE_EXTENSIONS = {".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls"}
INDEXABLE_EXTENSIONS = {".md", ".txt"}
ALL_SUPPORTED = PDF_EXTENSIONS | OFFICE_EXTENSIONS | INDEXABLE_EXTENSIONS


# ---------------------------------------------------------------------------
# Config bootstrap
# ---------------------------------------------------------------------------

def _setup_config(args: argparse.Namespace) -> None:
    from src.config.knowledge_base_config import load_knowledge_base_config_from_dict

    kb_dict: dict[str, Any] = {"enabled": True}

    if args.config:
        try:
            import yaml
            with open(args.config) as f:
                full = yaml.safe_load(f) or {}
            kb_dict = full.get("knowledge_base", {}) or {}
            kb_dict["enabled"] = True
            logger.info("Loaded knowledge_base config from %s", args.config)
        except Exception as exc:
            logger.error("Failed to load config.yaml: %s", exc)
            sys.exit(1)

    # CLI args always win over config.yaml
    mineru: dict[str, Any] = dict(kb_dict.get("mineru") or {})
    mineru["enabled"] = True
    if args.grpc_target is not None:
        mineru["target"] = args.grpc_target
    if args.api_token is not None:
        mineru["api_token"] = args.api_token
    if args.tls:
        mineru["use_tls"] = True
    if args.model_version is not None:
        mineru["model_version"] = args.model_version
    if args.request_timeout is not None:
        mineru["request_timeout"] = args.request_timeout
    if args.concurrency is not None:
        mineru["max_concurrent_ocr_jobs"] = args.concurrency

    if not mineru.get("target"):
        mineru["target"] = "127.0.0.1:50051"

    kb_dict["mineru"] = mineru
    load_knowledge_base_config_from_dict(kb_dict)
    logger.info("MinerU gRPC target: %s (tls=%s)", mineru["target"], mineru.get("use_tls", False))


# ---------------------------------------------------------------------------
# Ingestion record helpers
# ---------------------------------------------------------------------------

def _record_path(ingestion_dir: Path, filename: str) -> Path:
    return ingestion_dir / f"{filename}.json"


def _load_record(ingestion_dir: Path, filename: str) -> dict[str, Any] | None:
    path = _record_path(ingestion_dir, filename)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_record(ingestion_dir: Path, filename: str, record: dict[str, Any]) -> None:
    path = _record_path(ingestion_dir, filename)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def _new_record(filename: str, file_path: Path, hints: dict[str, str]) -> dict[str, Any]:
    return {
        "source_filename": filename,
        "display_title": file_path.stem,
        "source_extension": file_path.suffix.lower(),
        "source_size": file_path.stat().st_size,
        "content_type": "application/pdf",
        "parse_method": "ocr_pdf_mineru_grpc",
        "parse_status": "queued_ocr",
        "indexable": True,
        "source_artifact_url": None,
        "preview_filename": filename if file_path.suffix.lower() in INDEXABLE_EXTENSIONS else None,
        "preview_artifact_url": None,
        "structured_filename": None,
        "structured_path": None,
        "structured_artifact_url": None,
        "index_target_filename": None,
        "index_target_path": None,
        "index_target_artifact_url": None,
        "index_target_format": None,
        "hints": hints,
        "folder_path": None,
        "error": None,
        "replace_existing_index": False,
    }


def _mark_parsed(record: dict[str, Any], structured_filename: str, server_ingestion_dir: Path) -> dict[str, Any]:
    server_path = str(server_ingestion_dir / structured_filename)
    record.update(
        {
            "parse_status": "parsed",
            "structured_filename": structured_filename,
            "structured_path": server_path,
            "structured_artifact_url": None,
            "index_target_filename": structured_filename,
            "index_target_path": server_path,
            "index_target_artifact_url": None,
            "index_target_format": "structured_json",
            "error": None,
        }
    )
    return record


# ---------------------------------------------------------------------------
# Per-file processing
# ---------------------------------------------------------------------------

def _process_file(
    file_path: Path,
    ingestion_dir: Path,
    server_ingestion_dir: Path,
    disk_sem: threading.Semaphore,
    hints: dict[str, str],
    force: bool,
) -> str:
    from src.community.knowledge_base.mineru_grpc import build_structured_document_from_mineru_grpc
    from src.community.knowledge_base.structured_document import save_structured_document

    filename = file_path.name
    record = _load_record(ingestion_dir, filename) or _new_record(filename, file_path, hints)

    structured_out = ingestion_dir / f"{filename}.structured.json"
    if not force and record.get("parse_status") == "parsed" and structured_out.exists():
        return f"SKIP  {filename}  (already parsed)"

    record["parse_status"] = "parsing"
    record["error"] = None
    _save_record(ingestion_dir, filename, record)

    # Phase 1: read from disk (gated)
    with disk_sem:
        file_size = file_path.stat().st_size
        logger.info("READ  %s  (%.1f MB)", filename, file_size / 1_048_576)
        try:
            file_content = file_path.read_bytes()
        except OSError as exc:
            record["parse_status"] = "failed"
            record["error"] = f"read failed: {exc}"
            _save_record(ingestion_dir, filename, record)
            return f"FAIL  {filename}: {exc}"

    # Phase 2: remote OCR via gRPC (disk free)
    logger.info("OCR   %s  ...", filename)
    try:
        structured_payload = build_structured_document_from_mineru_grpc(
            file_path,
            title=str(record.get("display_title") or file_path.stem),
            parser_name="ocr_pdf_mineru_grpc",
            hints=hints,
            language_hint=hints.get("language_hint"),
            file_content=file_content,
        )
    except Exception as exc:
        record["parse_status"] = "failed"
        record["error"] = str(exc)
        _save_record(ingestion_dir, filename, record)
        logger.exception("OCR failed for %s", filename)
        return f"FAIL  {filename}: {exc}"
    finally:
        del file_content

    # Phase 3: write structured JSON to disk (gated)
    with disk_sem:
        logger.info("WRITE %s  (%d pages)", filename, len((structured_payload or {}).get("pages") or []))
        try:
            structured_path = save_structured_document(ingestion_dir, filename, structured_payload)
        except OSError as exc:
            record["parse_status"] = "failed"
            record["error"] = f"write failed: {exc}"
            _save_record(ingestion_dir, filename, record)
            return f"FAIL  {filename}: {exc}"

    record = _mark_parsed(record, structured_path.name, server_ingestion_dir)
    _save_record(ingestion_dir, filename, record)
    return f"OK    {filename}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run MinerU OCR locally and produce server-ready ingestion records.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("input", help="PDF file or directory containing PDFs")
    parser.add_argument("--grpc-target", default=None, metavar="HOST:PORT",
                        help="MinerU gRPC address (default: 127.0.0.1:50051)")
    parser.add_argument("--api-token", default=None, help="Bearer token for gRPC auth")
    parser.add_argument("--tls", action="store_true", help="Use TLS for gRPC")
    parser.add_argument("--model-version", default=None, help="MinerU model version (default: vlm)")
    parser.add_argument("--request-timeout", type=int, default=None,
                        help="gRPC timeout in seconds (default: 14400)")
    parser.add_argument("--concurrency", type=int, default=4,
                        help="Max parallel gRPC jobs (default: 4)")
    parser.add_argument("--disk-slots", type=int, default=2,
                        help="Max concurrent disk read/write operations (default: 2)")
    parser.add_argument("--server-docs-dir", default=None, metavar="PATH",
                        help="Absolute docs dir path ON THE SERVER. Embedded in ingestion records. "
                             "Defaults to the local input dir (ok for local testing only).")
    parser.add_argument("--language-hint", default=None, help='e.g. "zh", "en"')
    parser.add_argument("--layout-hint", default=None)
    parser.add_argument("--document-type-hint", default=None)
    parser.add_argument("--force", action="store_true",
                        help="Re-process files that already have a parsed record")
    parser.add_argument("--config", default=None, metavar="PATH",
                        help="Path to config.yaml; reads [knowledge_base] section")
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    if input_path.is_file():
        files = [input_path]
        input_dir = input_path.parent
    elif input_path.is_dir():
        files = sorted(p for p in input_path.iterdir()
                       if p.is_file() and p.suffix.lower() in ALL_SUPPORTED and not p.name.startswith("."))
        input_dir = input_path
    else:
        logger.error("Input path not found: %s", input_path)
        sys.exit(1)

    if not files:
        logger.warning("No supported files found in %s", input_path)
        sys.exit(0)

    # Where the files will live on the server (for path embedding)
    server_docs_dir = Path(args.server_docs_dir) if args.server_docs_dir else input_dir
    if server_docs_dir == input_dir and args.server_docs_dir is None:
        logger.warning(
            "--server-docs-dir not set; ingestion records will use local path %s.\n"
            "  This is only correct if you run the server on this same machine.\n"
            "  For cross-machine use: --server-docs-dir /path/on/server/knowledge/docs",
            input_dir,
        )

    server_ingestion_dir = server_docs_dir / ".ingestion"
    local_ingestion_dir = input_dir / ".ingestion"
    local_ingestion_dir.mkdir(exist_ok=True)

    hints: dict[str, str] = {}
    if args.language_hint:
        hints["language_hint"] = args.language_hint
    if args.layout_hint:
        hints["layout_hint"] = args.layout_hint
    if args.document_type_hint:
        hints["document_type_hint"] = args.document_type_hint

    _setup_config(args)

    disk_sem = threading.Semaphore(args.disk_slots)
    logger.info(
        "Files: %d  |  concurrency: %d  |  disk-slots: %d",
        len(files), args.concurrency, args.disk_slots,
    )

    ok = failed = skipped = 0
    with ThreadPoolExecutor(max_workers=args.concurrency, thread_name_prefix="ocr") as executor:
        futures = {
            executor.submit(
                _process_file,
                f, local_ingestion_dir, server_ingestion_dir, disk_sem, hints, args.force,
            ): f
            for f in files
        }
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as exc:
                result = f"FAIL  {futures[future].name}: unexpected: {exc}"
                logger.exception("Unexpected error processing %s", futures[future])
            logger.info(result)
            if result.startswith("OK"):
                ok += 1
            elif result.startswith("SKIP"):
                skipped += 1
            else:
                failed += 1

    logger.info("")
    logger.info("Results: %d ok, %d skipped, %d failed  (total %d)", ok, skipped, failed, len(files))

    if ok > 0:
        logger.info("")
        logger.info("Copy to server:")
        logger.info("  # Structured JSON + ingestion records:")
        logger.info("  rsync -av %s/  user@server:%s/", local_ingestion_dir, server_ingestion_dir)
        if server_docs_dir != input_dir:
            logger.info("  # Source PDFs (if not already on server):")
            logger.info("  rsync -av %s/*.pdf  user@server:%s/", input_dir, server_docs_dir)

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
