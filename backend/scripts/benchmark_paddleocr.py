from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

import fitz

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.community.knowledge_base.document_parsers import extract_pdf_text_with_paddleocr


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark local PaddleOCR at multiple DPI settings.")
    parser.add_argument("pdf", type=Path, help="Path to the PDF file to benchmark")
    parser.add_argument(
        "--dpi",
        type=int,
        nargs="+",
        default=[144, 160, 180],
        help="One or more DPI values to test",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=3,
        help="Number of pages from the beginning of the PDF to benchmark",
    )
    parser.add_argument(
        "--language-hint",
        default=None,
        help="Optional PaddleOCR language hint, e.g. ch, en, mixed, zh-Hant",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pdf_path = args.pdf.resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if args.pages <= 0:
        raise ValueError("--pages must be greater than 0")

    with fitz.open(pdf_path) as document:
        actual_pages = min(document.page_count, args.pages)

    print(f"Benchmarking {pdf_path}")
    print(f"Pages: first {actual_pages}")
    print()

    warmup_dpi = args.dpi[0]
    print(f"Warming up PaddleOCR at {warmup_dpi} DPI...")
    extract_pdf_text_with_paddleocr(
        pdf_path,
        language_hint=args.language_hint,
        dpi=warmup_dpi,
        page_limit=1,
    )
    print()

    summary: list[tuple[int, float, int]] = []
    for dpi in args.dpi:
        started_at = time.perf_counter()
        text = extract_pdf_text_with_paddleocr(
            pdf_path,
            language_hint=args.language_hint,
            dpi=dpi,
            page_limit=args.pages,
        )
        elapsed = time.perf_counter() - started_at
        chars = len(text)
        chars_per_page = chars / actual_pages
        summary.append((dpi, elapsed, chars))
        print(
            f"DPI {dpi:>3}: {elapsed:>7.2f}s total, "
            f"{elapsed / actual_pages:>6.2f}s/page, "
            f"{chars:>7} chars total, "
            f"{chars_per_page:>7.0f} chars/page"
        )

    print()
    ranked = sorted(summary, key=lambda item: item[1])
    fastest_dpi, fastest_elapsed, _ = ranked[0]
    avg_elapsed = statistics.mean(item[1] for item in summary)
    print(
        f"Fastest DPI: {fastest_dpi} "
        f"({fastest_elapsed:.2f}s total, average across tested DPIs {avg_elapsed:.2f}s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
