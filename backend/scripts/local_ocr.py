#!/usr/bin/env python3
"""
Run MinerU OCR locally on PDFs and write flat ingestion records.

One-shot mode (process files already in input dir, then exit):
    uv run python scripts/local_ocr.py --input ./pdfs --output ./res

Watch mode (keep running, pick up new files as they arrive):
    uv run python scripts/local_ocr.py --input ./pdfs --output ./res --watch

Output layout:
    res/
      book.pdf.json              <- ingestion record  (copy to server .ingestion/)
      book.pdf.structured.json   <- OCR output        (copy to server .ingestion/)
      done/
        book.pdf                 <- source PDF moved here after successful OCR

Ctrl-C to stop watch mode gracefully.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make 'src' importable regardless of where the script is invoked from
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import json
import logging
import shutil
import signal
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

ALL_SUPPORTED = {".pdf"}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _setup_config(args: argparse.Namespace) -> None:
    from src.config.knowledge_base_config import load_knowledge_base_config_from_dict

    kb: dict[str, Any] = {"enabled": True}
    if args.config:
        try:
            import yaml
            with open(args.config) as f:
                kb = (yaml.safe_load(f) or {}).get("knowledge_base", {}) or {}
            kb["enabled"] = True
        except Exception as exc:
            logger.error("Cannot load config.yaml: %s", exc)
            sys.exit(1)

    mineru: dict[str, Any] = dict(kb.get("mineru") or {})
    mineru["enabled"] = True
    if args.grpc_target:
        mineru["target"] = args.grpc_target
    if args.api_token:
        mineru["api_token"] = args.api_token
    if args.tls:
        mineru["use_tls"] = True
    if args.model_version:
        mineru["model_version"] = args.model_version
    if args.request_timeout:
        mineru["request_timeout"] = args.request_timeout
    mineru.setdefault("target", "127.0.0.1:50051")
    mineru.setdefault("max_concurrent_ocr_jobs", args.concurrency)
    kb["mineru"] = mineru
    load_knowledge_base_config_from_dict(kb)
    logger.info("gRPC  %s  tls=%s", mineru["target"], mineru.get("use_tls", False))


# ---------------------------------------------------------------------------
# Ingestion record helpers
# ---------------------------------------------------------------------------

def _record_path(output_dir: Path, filename: str) -> Path:
    return output_dir / f"{filename}.json"


def _load_record(output_dir: Path, filename: str) -> dict[str, Any] | None:
    p = _record_path(output_dir, filename)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_record(output_dir: Path, filename: str, record: dict[str, Any]) -> None:
    _record_path(output_dir, filename).write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _new_record(file_path: Path, hints: dict[str, str]) -> dict[str, Any]:
    filename = file_path.name
    suffix = file_path.suffix.lower()
    structured_filename = f"{filename}.structured.json"
    return {
        "source_filename": filename,
        "display_title": file_path.stem,
        "source_extension": suffix,
        "source_size": file_path.stat().st_size,
        "content_type": "application/pdf",
        "parse_method": "ocr_pdf_mineru_grpc",
        "parse_status": "queued_ocr",
        "indexable": True,
        "source_artifact_url": None,
        "preview_filename": None,
        "preview_artifact_url": None,
        # paths left None — server derives them from its own ingestion_dir + filename
        "structured_filename": structured_filename,
        "structured_path": None,
        "structured_artifact_url": None,
        "index_target_filename": structured_filename,
        "index_target_path": None,
        "index_target_artifact_url": None,
        "index_target_format": "structured_json",
        "hints": hints,
        "folder_path": None,
        "error": None,
        "replace_existing_index": False,
    }


# ---------------------------------------------------------------------------
# Per-file processing
# ---------------------------------------------------------------------------

def _process_file(
    file_path: Path,
    output_dir: Path,
    done_dir: Path,
    disk_sem: threading.Semaphore,
    hints: dict[str, str],
    force: bool,
) -> str:
    from src.community.knowledge_base.mineru_grpc import build_structured_document_from_mineru_grpc
    from src.community.knowledge_base.structured_document import save_structured_document

    filename = file_path.name
    record = _load_record(output_dir, filename) or _new_record(file_path, hints)

    structured_out = output_dir / f"{filename}.structured.json"
    if not force and record.get("parse_status") == "parsed" and structured_out.exists():
        return f"SKIP  {filename}"

    record["parse_status"] = "parsing"
    record["error"] = None
    _save_record(output_dir, filename, record)

    # Phase 1: read (gated)
    with disk_sem:
        mb = file_path.stat().st_size / 1_048_576
        logger.info("READ  %s  (%.1f MB)", filename, mb)
        try:
            file_content = file_path.read_bytes()
        except OSError as exc:
            record.update({"parse_status": "failed", "error": f"read: {exc}"})
            _save_record(output_dir, filename, record)
            return f"FAIL  {filename}: {exc}"

    # Phase 2: OCR via gRPC (disk free)
    logger.info("OCR   %s ...", filename)
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
        record.update({"parse_status": "failed", "error": str(exc)})
        _save_record(output_dir, filename, record)
        logger.exception("OCR failed: %s", filename)
        return f"FAIL  {filename}: {exc}"
    finally:
        del file_content

    # Phase 3: write JSON (gated)
    with disk_sem:
        pages = len((structured_payload or {}).get("pages") or [])
        logger.info("WRITE %s  (%d pages)", filename, pages)
        try:
            save_structured_document(output_dir, filename, structured_payload)
        except OSError as exc:
            record.update({"parse_status": "failed", "error": f"write: {exc}"})
            _save_record(output_dir, filename, record)
            return f"FAIL  {filename}: {exc}"

    structured_filename = f"{filename}.structured.json"
    record.update({
        "parse_status": "parsed",
        "structured_filename": structured_filename,
        "structured_path": None,
        "index_target_filename": structured_filename,
        "index_target_path": None,
        "index_target_format": "structured_json",
        "error": None,
    })
    _save_record(output_dir, filename, record)

    # Move source PDF to done/
    dest = done_dir / filename
    try:
        shutil.move(str(file_path), dest)
        logger.info("MOVED %s → done/", filename)
    except OSError as exc:
        logger.warning("Could not move %s: %s", filename, exc)

    return f"OK    {filename}"


# ---------------------------------------------------------------------------
# Watch loop
# ---------------------------------------------------------------------------

def _scan_for_new(
    input_dir: Path,
    output_dir: Path,
    inflight: set[str],
    force: bool,
) -> list[Path]:
    """Return files in input_dir that are not yet processed or in-flight."""
    candidates = []
    for p in sorted(input_dir.iterdir()):
        if not p.is_file():
            continue
        if p.suffix.lower() not in ALL_SUPPORTED:
            continue
        if p.name.startswith("."):
            continue
        if p.name in inflight:
            continue
        record = _load_record(output_dir, p.name)
        structured_out = output_dir / f"{p.name}.structured.json"
        if not force and record and record.get("parse_status") == "parsed" and structured_out.exists():
            continue
        candidates.append(p)
    return candidates


def _run(args: argparse.Namespace) -> int:
    input_dir = Path(args.input).resolve()
    output_dir = Path(args.output).resolve()
    done_dir = output_dir / "done"

    if not input_dir.is_dir():
        logger.error("Input directory not found: %s", input_dir)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    done_dir.mkdir(exist_ok=True)

    hints: dict[str, str] = {}
    for key, val in [
        ("language_hint", args.language_hint),
        ("layout_hint", args.layout_hint),
        ("document_type_hint", args.document_type_hint),
    ]:
        if val:
            hints[key] = val

    _setup_config(args)

    disk_sem = threading.Semaphore(args.disk_slots)
    inflight: set[str] = set()
    inflight_lock = threading.Lock()
    futures: dict[Future, str] = {}

    def _handle_sigint(*_):
        logger.info("Interrupted — exiting.")
        os._exit(0)

    signal.signal(signal.SIGINT, _handle_sigint)
    signal.signal(signal.SIGTERM, _handle_sigint)

    ok = failed = skipped = 0

    with ThreadPoolExecutor(max_workers=args.concurrency, thread_name_prefix="ocr") as pool:
        while not stop_event.is_set():
            # Collect results from finished futures
            done_futures = [f for f in list(futures) if f.done()]
            for fut in done_futures:
                fname = futures.pop(fut)
                with inflight_lock:
                    inflight.discard(fname)
                try:
                    result = fut.result()
                except Exception as exc:
                    result = f"FAIL  {fname}: {exc}"
                    logger.exception("Unexpected: %s", fname)
                logger.info(result)
                if result.startswith("OK"):
                    ok += 1
                elif result.startswith("SKIP"):
                    skipped += 1
                else:
                    failed += 1

            # Submit new files
            with inflight_lock:
                current_inflight = set(inflight)
            new_files = _scan_for_new(input_dir, output_dir, current_inflight, args.force)
            for file_path in new_files:
                with inflight_lock:
                    inflight.add(file_path.name)
                fut = pool.submit(
                    _process_file,
                    file_path, output_dir, done_dir, disk_sem, hints, args.force,
                )
                futures[fut] = file_path.name
                logger.info("QUEUE %s", file_path.name)

            if not args.watch:
                if not futures:
                    break
            else:
                if not new_files and not futures:
                    logger.debug("Watching %s (poll every %ds) ...", input_dir, args.poll_interval)
                time.sleep(args.poll_interval)

        # Drain remaining futures after stop
        for fut, fname in list(futures.items()):
            try:
                result = fut.result()
            except Exception as exc:
                result = f"FAIL  {fname}: {exc}"
            logger.info(result)
            if result.startswith("OK"):
                ok += 1
            elif result.startswith("SKIP"):
                skipped += 1
            else:
                failed += 1

    logger.info("Done: %d ok  %d skipped  %d failed", ok, skipped, failed)
    logger.info("Output: %s", output_dir)
    return 1 if failed else 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run MinerU OCR locally; output flat ingestion records.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input", required=True, metavar="DIR",
                        help="Directory to watch for PDF files")
    parser.add_argument("--output", required=True, metavar="DIR",
                        help="Output directory for JSON files (PDFs moved to output/done/)")
    parser.add_argument("--watch", action="store_true",
                        help="Keep running and pick up new files as they appear")
    parser.add_argument("--poll-interval", type=int, default=10, metavar="SEC",
                        help="Seconds between directory scans in watch mode (default: 10)")
    parser.add_argument("--grpc-target", default=None, metavar="HOST:PORT")
    parser.add_argument("--api-token", default=None)
    parser.add_argument("--tls", action="store_true")
    parser.add_argument("--model-version", default=None)
    parser.add_argument("--request-timeout", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=4,
                        help="Max parallel gRPC jobs (default: 4)")
    parser.add_argument("--disk-slots", type=int, default=2,
                        help="Max concurrent disk reads/writes (default: 2)")
    parser.add_argument("--language-hint", default=None)
    parser.add_argument("--layout-hint", default=None)
    parser.add_argument("--document-type-hint", default=None)
    parser.add_argument("--force", action="store_true",
                        help="Re-process files that already have a parsed record")
    parser.add_argument("--config", default=None, metavar="PATH",
                        help="config.yaml — reads [knowledge_base] section")
    args = parser.parse_args()

    sys.exit(_run(args))


if __name__ == "__main__":
    main()
