#!/usr/bin/env python3
"""Smoke test script for the MinerU gRPC service."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

import grpc

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.community.knowledge_base.mineru_grpc import (  # noqa: E402
    MAX_GRPC_MESSAGE_BYTES,
    build_structured_document_from_mineru_response,
)
from src.community.knowledge_base.mineru_proto import mineru_pb2, mineru_pb2_grpc  # noqa: E402


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _build_channel(target: str, use_tls: bool) -> grpc.Channel:
    options = [
        ("grpc.max_send_message_length", MAX_GRPC_MESSAGE_BYTES),
        ("grpc.max_receive_message_length", MAX_GRPC_MESSAGE_BYTES),
    ]
    if use_tls:
        return grpc.secure_channel(target, grpc.ssl_channel_credentials(), options=options)
    return grpc.insecure_channel(target, options=options)


def _build_request(args: argparse.Namespace, pdf_path: Path) -> mineru_pb2.ParsePdfRequest:
    return mineru_pb2.ParsePdfRequest(
        filename=pdf_path.name,
        file_content=pdf_path.read_bytes(),
        language_hint=args.language_hint or "",
        layout_hint=args.layout_hint or "",
        document_type_hint=args.document_type_hint or "",
        book_page_start_pdf_page=args.book_page_start_pdf_page or "",
        book_page_start_value=args.book_page_start_value or "",
        model_version=args.model_version or "",
    )


def _build_metadata(token: str | None) -> list[tuple[str, str]]:
    if not token:
        return []
    return [("authorization", f"Bearer {token}")]


def _print_summary(response: mineru_pb2.ParsePdfResponse, normalized: dict | None) -> None:
    print("MinerU gRPC call succeeded")
    print(f"task_id: {response.task_id or '-'}")
    print(f"proto_pages: {len(response.document.pages)}")
    print(f"proto_full_text_chars: {len(response.document.full_text or '')}")

    if normalized is None:
        return

    pages = normalized.get("pages") or []
    paragraph_count = sum(len(page.get("paragraphs") or []) for page in pages)
    print(f"normalized_pages: {len(pages)}")
    print(f"normalized_paragraphs: {paragraph_count}")
    print(f"normalized_full_text_chars: {len(normalized.get('full_text') or '')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Call the MinerU gRPC ParsePdf service with a local PDF.")
    parser.add_argument("pdf", type=Path, help="Path to the local PDF file")
    parser.add_argument(
        "--target",
        default=os.getenv("MINERU_GRPC_TARGET", "127.0.0.1:50051"),
        help="gRPC target in host:port form",
    )
    parser.add_argument(
        "--use-tls",
        action="store_true",
        default=_parse_bool(os.getenv("MINERU_GRPC_USE_TLS"), default=False),
        help="Use TLS for the gRPC connection",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("MINERU_API_TOKEN"),
        help="Optional bearer token sent as gRPC metadata",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Request timeout in seconds",
    )
    parser.add_argument(
        "--language-hint",
        default=None,
        help="Optional language hint, e.g. zh, en, zh-Hant",
    )
    parser.add_argument(
        "--layout-hint",
        default=None,
        help="Optional layout hint, e.g. horizontal, vertical, mixed",
    )
    parser.add_argument(
        "--document-type-hint",
        default=None,
        help="Optional document type hint, e.g. book, ancient_book, periodical",
    )
    parser.add_argument(
        "--book-page-start-pdf-page",
        default=None,
        help="Optional first PDF page that maps to a book page number",
    )
    parser.add_argument(
        "--book-page-start-value",
        default=None,
        help="Optional book page number corresponding to --book-page-start-pdf-page",
    )
    parser.add_argument(
        "--model-version",
        default=os.getenv("MINERU_MODEL_VERSION", "vlm"),
        help="Model version sent to the MinerU service",
    )
    parser.add_argument(
        "--dump-json",
        type=Path,
        default=None,
        help="Optional output path for the normalized structured json",
    )
    args = parser.parse_args()

    pdf_path = args.pdf.expanduser().resolve()
    if not pdf_path.exists() or not pdf_path.is_file():
        print(f"PDF not found: {pdf_path}", file=sys.stderr)
        return 1

    request = _build_request(args, pdf_path)
    metadata = _build_metadata(args.token)

    try:
        with _build_channel(args.target, args.use_tls) as channel:
            stub = mineru_pb2_grpc.MineruPdfExtractorStub(channel)
            response = stub.ParsePdf(
                request,
                timeout=args.timeout,
                metadata=metadata,
            )
    except grpc.RpcError as exc:
        print(
            f"MinerU gRPC failed: code={exc.code().name} details={exc.details()}",
            file=sys.stderr,
        )
        return 2

    normalized = build_structured_document_from_mineru_response(
        source_filename=pdf_path.name,
        title=pdf_path.stem,
        parser_name="ocr_pdf_mineru_grpc",
        response=response,
        hints={
            key: value
            for key, value in {
                "language_hint": args.language_hint,
                "layout_hint": args.layout_hint,
                "document_type_hint": args.document_type_hint,
                "book_page_start_pdf_page": args.book_page_start_pdf_page,
                "book_page_start_value": args.book_page_start_value,
            }.items()
            if value
        },
    )
    _print_summary(response, normalized)

    if args.dump_json is not None:
        output_path = args.dump_json.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"normalized_json_written: {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
