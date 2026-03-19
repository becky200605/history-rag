"""Document parsing helpers for OCR and text extraction."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
import logging
import os
import re
from statistics import median
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.community.knowledge_base.structured_document import (
    build_bbox,
    build_page_reference,
)

logger = logging.getLogger(__name__)

PDF_EXTENSIONS = {".pdf"}
OFFICE_EXTENSIONS = {
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".doc",
    ".docx",
}


def infer_parse_method(filename: str) -> tuple[str, bool]:
    """Infer the parser used for a given source file."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".md":
        return "markdown", True
    if suffix == ".txt":
        return "plain_text", True
    if suffix in PDF_EXTENSIONS:
        return "ocr_pdf", True
    if suffix in OFFICE_EXTENSIONS:
        return "markitdown_office", True
    return "binary_only", False


def choose_pdf_parse_backend(hints: dict[str, str] | None = None) -> str:
    """Choose the PDF parser backend based on user hints.

    Returns:
        "local_paddleocr" for low-cost local parsing
        "baidu_doc_parser" for complex layouts that benefit from remote parsing
    """
    hints = hints or {}
    layout_hint = hints.get("layout_hint")
    language_hint = hints.get("language_hint")
    document_type_hint = hints.get("document_type_hint")

    if layout_hint == "horizontal":
        return "local_paddleocr"
    if layout_hint in {"vertical", "mixed"}:
        return "baidu_doc_parser"
    if document_type_hint in {"ancient_book", "periodical"}:
        return "baidu_doc_parser"
    if language_hint == "zh-Hant":
        return "baidu_doc_parser"
    return "local_paddleocr"


def _resolve_paddleocr_lang(language_hint: str | None) -> str:
    if language_hint == "zh-Hant":
        return "chinese_cht"
    if language_hint in {"en", "mixed"}:
        return "en"
    return "ch"


def _resolve_local_pdf_ocr_dpi() -> int:
    dpi = _parse_env_int("LOCAL_PDF_OCR_DPI", default=160, minimum=72, maximum=600)
    return dpi


def _parse_env_int(
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw_value = (os.getenv(name) or "").strip()
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        logger.warning("Invalid %s=%r, falling back to %s", name, raw_value, default)
        return default
    if value < minimum or value > maximum:
        logger.warning(
            "Out-of-range %s=%s, falling back to %s",
            name,
            value,
            default,
        )
        return default
    return value


def _parse_optional_env_int(
    name: str,
    *,
    minimum: int,
    maximum: int,
) -> int | None:
    raw_value = (os.getenv(name) or "").strip()
    if not raw_value:
        return None
    try:
        value = int(raw_value)
    except ValueError:
        logger.warning("Invalid %s=%r, ignoring it", name, raw_value)
        return None
    if value < minimum or value > maximum:
        logger.warning("Out-of-range %s=%s, ignoring it", name, value)
        return None
    return value


def _parse_env_bool(name: str, *, default: bool) -> bool:
    raw_value = (os.getenv(name) or "").strip().lower()
    if not raw_value:
        return default
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    logger.warning("Invalid %s=%r, falling back to %s", name, raw_value, default)
    return default


def _resolve_local_pdf_ocr_runtime_options(dpi: int | None = None) -> dict[str, Any]:
    return {
        "dpi": dpi or _resolve_local_pdf_ocr_dpi(),
        "cpu_threads": _parse_optional_env_int(
            "LOCAL_PDF_OCR_CPU_THREADS",
            minimum=1,
            maximum=64,
        ),
        "enable_mkldnn": _parse_env_bool(
            "LOCAL_PDF_OCR_ENABLE_MKLDNN",
            default=False,
        ),
        "det_limit_side_len": _parse_optional_env_int(
            "LOCAL_PDF_OCR_DET_LIMIT_SIDE_LEN",
            minimum=64,
            maximum=4096,
        ),
        "use_textline_orientation": _parse_env_bool(
            "LOCAL_PDF_OCR_USE_TEXTLINE_ORIENTATION",
            default=True,
        ),
        "workers": _parse_env_int(
            "LOCAL_PDF_OCR_WORKERS",
            default=1,
            minimum=1,
            maximum=16,
        ),
    }


@lru_cache(maxsize=16)
def _get_paddleocr(
    lang: str,
    cpu_threads: int | None,
    enable_mkldnn: bool,
    det_limit_side_len: int | None,
    use_textline_orientation: bool,
):
    from paddleocr import PaddleOCR

    paddle_kwargs: dict[str, Any] = {
        "lang": lang,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": use_textline_orientation,
        "enable_mkldnn": enable_mkldnn,
    }
    if cpu_threads is not None:
        paddle_kwargs["cpu_threads"] = cpu_threads
    if det_limit_side_len is not None:
        paddle_kwargs["det_limit_side_len"] = det_limit_side_len

    return PaddleOCR(**paddle_kwargs)


def _collect_text_fragments(node: Any, fragments: list[str]) -> None:
    """Collect OCR text fragments from PaddleOCR output structures."""
    if node is None:
        return
    if isinstance(node, str):
        text = node.strip()
        if text:
            fragments.append(text)
        return
    if isinstance(node, list):
        for item in node:
            _collect_text_fragments(item, fragments)
        return
    if isinstance(node, dict):
        rec_texts = node.get("rec_texts")
        if isinstance(rec_texts, list):
            for text in rec_texts:
                if isinstance(text, str) and text.strip():
                    fragments.append(text.strip())
        for key in ("text", "rec_text", "transcription"):
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                fragments.append(value.strip())
        for value in node.values():
            _collect_text_fragments(value, fragments)
        return

    for attr in ("res", "result", "ocr_result", "data"):
        value = getattr(node, attr, None)
        if value is not None:
            _collect_text_fragments(value, fragments)


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _extract_page_text(page_result: Any) -> str:
    fragments: list[str] = []
    if not isinstance(page_result, list):
        _collect_text_fragments(page_result, fragments)
    else:
        for line in page_result:
            if (
                isinstance(line, list)
                and len(line) >= 2
                and isinstance(line[1], (list, tuple))
                and line[1]
                and isinstance(line[1][0], str)
            ):
                text = line[1][0].strip()
                if text:
                    fragments.append(text)
            else:
                _collect_text_fragments(line, fragments)
    return "\n".join(_dedupe_preserve_order(fragments)).strip()


def _polygon_to_bbox(polygon: Any) -> dict[str, float] | None:
    if not isinstance(polygon, (list, tuple)) or not polygon:
        return None
    points: list[tuple[float, float]] = []
    for point in polygon:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        try:
            x = float(point[0])
            y = float(point[1])
        except (TypeError, ValueError):
            continue
        points.append((x, y))
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    left = min(xs)
    top = min(ys)
    right = max(xs)
    bottom = max(ys)
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        return None
    return build_bbox(x=left, y=top, width=width, height=height)


def _extract_page_lines(page_result: Any) -> list[dict[str, Any]]:
    if not isinstance(page_result, list):
        return []

    lines: list[dict[str, Any]] = []
    for line in page_result:
        if not (
            isinstance(line, list)
            and len(line) >= 2
            and isinstance(line[0], (list, tuple))
            and isinstance(line[1], (list, tuple))
            and line[1]
            and isinstance(line[1][0], str)
        ):
            continue
        text = line[1][0].strip()
        if not text:
            continue
        confidence = None
        if len(line[1]) > 1:
            try:
                confidence = float(line[1][1])
            except (TypeError, ValueError):
                confidence = None
        bbox = _polygon_to_bbox(line[0])
        lines.append(
            {
                "text": text,
                "bbox": bbox,
                "polygon": line[0],
                "confidence": confidence,
            }
        )

    def _sort_key(item: dict[str, Any]) -> tuple[float, float]:
        bbox = item.get("bbox") or {}
        return (
            float(bbox.get("y", 0.0)),
            float(bbox.get("x", 0.0)),
        )

    return sorted(lines, key=_sort_key)


def _merge_line_bboxes(lines: list[dict[str, Any]]) -> dict[str, float] | None:
    boxes = [line.get("bbox") for line in lines if isinstance(line.get("bbox"), dict)]
    if not boxes:
        return None

    left = min(float(box["x"]) for box in boxes)
    top = min(float(box["y"]) for box in boxes)
    right = max(float(box["x"]) + float(box["width"]) for box in boxes)
    bottom = max(float(box["y"]) + float(box["height"]) for box in boxes)
    return build_bbox(x=left, y=top, width=right - left, height=bottom - top)


def _is_paragraph_break_text(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return True
    if normalized.endswith(("。", "！", "？", "；", ";", "：", ":")):
        return True
    if re.match(r"^(第[一二三四五六七八九十百千万0-9]+[章节篇部]|附[录表]|注[:：])", normalized):
        return True
    return False


def _should_insert_space(previous_text: str, current_text: str) -> bool:
    if not previous_text or not current_text:
        return False
    prev_char = previous_text[-1]
    next_char = current_text[0]
    return prev_char.isascii() and prev_char.isalnum() and next_char.isascii() and next_char.isalnum()


def _join_paragraph_lines(lines: list[dict[str, Any]]) -> str:
    merged = ""
    for line in lines:
        text = str(line.get("text") or "").strip()
        if not text:
            continue
        if not merged:
            merged = text
            continue
        merged += (" " if _should_insert_space(merged, text) else "") + text
    return merged.strip()


def _should_merge_ocr_lines(
    previous_line: dict[str, Any],
    current_line: dict[str, Any],
    *,
    median_height: float,
    page_width: int,
) -> bool:
    previous_bbox = previous_line.get("bbox")
    current_bbox = current_line.get("bbox")
    if not isinstance(previous_bbox, dict) or not isinstance(current_bbox, dict):
        return False

    previous_bottom = float(previous_bbox["y"]) + float(previous_bbox["height"])
    current_top = float(current_bbox["y"])
    vertical_gap = current_top - previous_bottom
    max_gap = max(18.0, median_height * 0.9)
    if vertical_gap < -(median_height * 0.35) or vertical_gap > max_gap:
        return False

    left_tolerance = max(24.0, page_width * 0.012)
    if abs(float(previous_bbox["x"]) - float(current_bbox["x"])) > left_tolerance:
        return False

    previous_right = float(previous_bbox["x"]) + float(previous_bbox["width"])
    current_right = float(current_bbox["x"]) + float(current_bbox["width"])
    horizontal_overlap = max(
        0.0,
        min(previous_right, current_right) - max(float(previous_bbox["x"]), float(current_bbox["x"])),
    )
    min_width = min(float(previous_bbox["width"]), float(current_bbox["width"]))
    overlap_ratio = horizontal_overlap / min_width if min_width > 0 else 0.0
    right_tolerance = max(36.0, page_width * 0.02)
    if overlap_ratio < 0.6 and abs(previous_right - current_right) > right_tolerance:
        return False

    previous_text = str(previous_line.get("text") or "").strip()
    current_text = str(current_line.get("text") or "").strip()
    if not previous_text or not current_text:
        return False
    if _is_paragraph_break_text(previous_text):
        return False
    if re.match(r"^[#（(【\[]?[一二三四五六七八九十0-9]{1,3}[）)】\]]", current_text):
        return False

    return True


def _group_ocr_lines_into_paragraphs(
    *,
    page_lines: list[dict[str, Any]],
    page_width: int,
) -> list[dict[str, Any]]:
    if not page_lines:
        return []

    line_heights = [
        float((line.get("bbox") or {}).get("height", 0.0))
        for line in page_lines
        if isinstance(line.get("bbox"), dict) and float((line.get("bbox") or {}).get("height", 0.0)) > 0
    ]
    median_height = median(line_heights) if line_heights else 0.0

    groups: list[list[dict[str, Any]]] = []
    current_group: list[dict[str, Any]] = []
    for line in page_lines:
        if not current_group:
            current_group = [line]
            continue
        if _should_merge_ocr_lines(
            current_group[-1],
            line,
            median_height=median_height,
            page_width=page_width,
        ):
            current_group.append(line)
        else:
            groups.append(current_group)
            current_group = [line]

    if current_group:
        groups.append(current_group)

    paragraphs: list[dict[str, Any]] = []
    for group in groups:
        merged_text = _join_paragraph_lines(group)
        if not merged_text:
            continue
        confidences = [
            float(confidence)
            for confidence in (line.get("confidence") for line in group)
            if isinstance(confidence, (int, float))
        ]
        paragraphs.append(
            {
                "text": merged_text,
                "bbox": _merge_line_bboxes(group),
                "confidence": (sum(confidences) / len(confidences)) if confidences else None,
                "line_count": len(group),
                "source_lines": group,
            }
        )

    return paragraphs


def _build_page_payload_from_ocr_lines(
    *,
    page_index: int,
    hints: dict[str, str] | None,
    page_width: int,
    page_height: int,
    page_lines: list[dict[str, Any]],
    paragraph_no_in_doc_start: int,
    global_line_start: int,
) -> tuple[dict[str, Any], int, int]:
    page_reference = build_page_reference(page_index, hints)
    paragraphs: list[dict[str, Any]] = []
    page_text_lines: list[str] = []
    global_line = global_line_start
    paragraph_no_in_doc = paragraph_no_in_doc_start

    page_paragraphs = _group_ocr_lines_into_paragraphs(
        page_lines=page_lines,
        page_width=page_width,
    )

    for paragraph_no_on_page, paragraph_source in enumerate(page_paragraphs, start=1):
        text = str(paragraph_source.get("text") or "").strip()
        if not text:
            continue
        line_count = max(1, int(paragraph_source.get("line_count") or 1))
        paragraph = {
            "paragraph_id": f"page-{page_reference['page_no']}-p{paragraph_no_on_page}",
            "paragraph_no": paragraph_no_on_page,
            "paragraph_no_in_doc": paragraph_no_in_doc,
            "text": text,
            "line_start": global_line,
            "line_end": global_line + line_count - 1,
            "bbox": paragraph_source.get("bbox"),
            "bbox_source": "paddleocr_merged_lines",
            "confidence": paragraph_source.get("confidence"),
            "source_line_count": line_count,
        }
        paragraphs.append(paragraph)
        page_text_lines.append(text)
        global_line += line_count + 1
        paragraph_no_in_doc += 1

    page_payload = {
        **page_reference,
        "text": "\n".join(page_text_lines).strip(),
        "paragraphs": paragraphs,
        "meta": {
            "page_width": page_width,
            "page_height": page_height,
            "is_scan": True,
            "page_type": "doc",
        },
    }
    return page_payload, paragraph_no_in_doc, global_line


def _ocr_pdf_page_in_worker(
    file_path_str: str,
    file_name: str,
    page_index: int,
    max_pages: int,
    lang: str,
    dpi: int,
    cpu_threads: int | None,
    enable_mkldnn: bool,
    det_limit_side_len: int | None,
    use_textline_orientation: bool,
) -> tuple[int, str, float]:
    import fitz
    import numpy as np

    logger.info(
        "PaddleOCR starting %s page %s/%s at %s DPI (worker)",
        file_name,
        page_index + 1,
        max_pages,
        dpi,
    )
    with fitz.open(file_path_str) as document:
        page = document.load_page(page_index)
        pixmap = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
        image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
            pixmap.height,
            pixmap.width,
            3,
        )

    ocr = _get_paddleocr(
        lang,
        cpu_threads,
        enable_mkldnn,
        det_limit_side_len,
        use_textline_orientation,
    )
    page_started_at = time.perf_counter()
    result = ocr.ocr(image, cls=False)
    page_elapsed = time.perf_counter() - page_started_at
    page_result = result[0] if isinstance(result, list) and len(result) == 1 else result
    return page_index, _extract_page_text(page_result), page_elapsed


def _ocr_pdf_page_payload_in_worker(
    file_path_str: str,
    file_name: str,
    page_index: int,
    max_pages: int,
    lang: str,
    dpi: int,
    cpu_threads: int | None,
    enable_mkldnn: bool,
    det_limit_side_len: int | None,
    use_textline_orientation: bool,
) -> tuple[int, dict[str, Any], float]:
    import fitz
    import numpy as np

    logger.info(
        "PaddleOCR structured parse starting %s page %s/%s at %s DPI (worker)",
        file_name,
        page_index + 1,
        max_pages,
        dpi,
    )
    with fitz.open(file_path_str) as document:
        page = document.load_page(page_index)
        pixmap = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
        image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
            pixmap.height,
            pixmap.width,
            3,
        )

    ocr = _get_paddleocr(
        lang,
        cpu_threads,
        enable_mkldnn,
        det_limit_side_len,
        use_textline_orientation,
    )
    page_started_at = time.perf_counter()
    result = ocr.ocr(image, cls=False)
    page_elapsed = time.perf_counter() - page_started_at
    page_result = result[0] if isinstance(result, list) and len(result) == 1 else result
    return (
        page_index,
        {
            "page_width": pixmap.width,
            "page_height": pixmap.height,
            "page_lines": _extract_page_lines(page_result),
        },
        page_elapsed,
    )


def extract_pdf_text_with_paddleocr(
    file_path: Path,
    language_hint: str | None = None,
    *,
    dpi: int | None = None,
    page_limit: int | None = None,
) -> str:
    """Render PDF pages at a controlled DPI and OCR them with PaddleOCR."""
    import fitz
    import numpy as np

    lang = _resolve_paddleocr_lang(language_hint)
    options = _resolve_local_pdf_ocr_runtime_options(dpi)
    effective_dpi = int(options["dpi"])
    cpu_threads = options["cpu_threads"]
    enable_mkldnn = bool(options["enable_mkldnn"])
    det_limit_side_len = options["det_limit_side_len"]
    use_textline_orientation = bool(options["use_textline_orientation"])
    configured_workers = int(options["workers"])
    logger.info(
        "Running PaddleOCR on %s with lang=%s dpi=%s page_limit=%s workers=%s cpu_threads=%s mkldnn=%s det_limit_side_len=%s textline_orientation=%s",
        file_path.name,
        lang,
        effective_dpi,
        page_limit,
        configured_workers,
        cpu_threads,
        enable_mkldnn,
        det_limit_side_len,
        use_textline_orientation,
    )

    page_texts: list[str] = []
    start_time = time.perf_counter()
    with fitz.open(file_path) as document:
        total_pages = document.page_count
        max_pages = total_pages if page_limit is None else min(total_pages, page_limit)
        if max_pages <= 0:
            raise ValueError("page_limit must be greater than 0")
        effective_workers = min(configured_workers, max_pages)
        if effective_workers > 1:
            logger.info(
                "Running PaddleOCR worker pool for %s with %s processes",
                file_path.name,
                effective_workers,
            )
            page_texts_by_index: dict[int, str] = {}
            with ProcessPoolExecutor(max_workers=effective_workers) as executor:
                future_to_page = {
                    executor.submit(
                        _ocr_pdf_page_in_worker,
                        str(file_path),
                        file_path.name,
                        page_index,
                        max_pages,
                        lang,
                        effective_dpi,
                        cpu_threads,
                        enable_mkldnn,
                        det_limit_side_len,
                        use_textline_orientation,
                    ): page_index
                    for page_index in range(max_pages)
                }
                for future in as_completed(future_to_page):
                    page_index = future_to_page[future]
                    try:
                        processed_page_index, page_text, page_elapsed = future.result()
                    except Exception as exc:
                        raise RuntimeError(
                            f"PaddleOCR failed on {file_path.name} page {page_index + 1}/{max_pages}: {exc}"
                        ) from exc
                    if page_text:
                        page_texts_by_index[processed_page_index] = page_text
                    logger.info(
                        "PaddleOCR processed %s page %s/%s in %.2fs at %s DPI (worker)",
                        file_path.name,
                        processed_page_index + 1,
                        max_pages,
                        page_elapsed,
                        effective_dpi,
                    )
            page_texts = [
                page_texts_by_index[page_index]
                for page_index in range(max_pages)
                if page_index in page_texts_by_index
            ]
        else:
            ocr = _get_paddleocr(
                lang,
                cpu_threads,
                enable_mkldnn,
                det_limit_side_len,
                use_textline_orientation,
            )
            for page_index in range(max_pages):
                page = document.load_page(page_index)
                logger.info(
                    "PaddleOCR starting %s page %s/%s at %s DPI",
                    file_path.name,
                    page_index + 1,
                    max_pages,
                    effective_dpi,
                )
                pixmap = page.get_pixmap(dpi=effective_dpi, colorspace=fitz.csRGB, alpha=False)
                image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                    pixmap.height,
                    pixmap.width,
                    3,
                )

                page_started_at = time.perf_counter()
                result = ocr.ocr(image, cls=False)
                page_elapsed = time.perf_counter() - page_started_at
                page_result = result[0] if isinstance(result, list) and len(result) == 1 else result
                page_text = _extract_page_text(page_result)
                if page_text:
                    page_texts.append(page_text)
                logger.info(
                    "PaddleOCR processed %s page %s/%s in %.2fs at %s DPI",
                    file_path.name,
                    page_index + 1,
                    max_pages,
                    page_elapsed,
                    effective_dpi,
                )
    text = "\f".join(page_texts).strip()
    if not text:
        raise ValueError("PaddleOCR returned no text")
    elapsed = time.perf_counter() - start_time
    logger.info(
        "PaddleOCR extracted %s chars across %s/%s page(s) from %s in %.2fs at %s DPI",
        len(text),
        len(page_texts),
        max_pages,
        file_path.name,
        elapsed,
        effective_dpi,
    )
    return text


def build_structured_document_from_paddleocr(
    file_path: Path,
    *,
    title: str,
    parser_name: str,
    hints: dict[str, str] | None = None,
    language_hint: str | None = None,
    dpi: int | None = None,
    page_limit: int | None = None,
) -> dict[str, Any]:
    """Render PDF pages and keep paragraph-level bbox metadata from PaddleOCR."""
    import fitz
    import numpy as np

    hints = hints or {}
    lang = _resolve_paddleocr_lang(language_hint)
    options = _resolve_local_pdf_ocr_runtime_options(dpi)
    effective_dpi = int(options["dpi"])
    cpu_threads = options["cpu_threads"]
    enable_mkldnn = bool(options["enable_mkldnn"])
    det_limit_side_len = options["det_limit_side_len"]
    use_textline_orientation = bool(options["use_textline_orientation"])
    configured_workers = int(options["workers"])

    pages: list[dict[str, Any]] = []
    page_texts: list[str] = []
    paragraph_no_in_doc = 1
    global_line = 1

    with fitz.open(file_path) as document:
        total_pages = document.page_count
        max_pages = total_pages if page_limit is None else min(total_pages, page_limit)
        if max_pages <= 0:
            raise ValueError("page_limit must be greater than 0")

        page_payloads_by_index: dict[int, dict[str, Any]] = {}
        effective_workers = min(configured_workers, max_pages)
        if effective_workers > 1:
            with ProcessPoolExecutor(max_workers=effective_workers) as executor:
                future_to_page = {
                    executor.submit(
                        _ocr_pdf_page_payload_in_worker,
                        str(file_path),
                        file_path.name,
                        page_index,
                        max_pages,
                        lang,
                        effective_dpi,
                        cpu_threads,
                        enable_mkldnn,
                        det_limit_side_len,
                        use_textline_orientation,
                    ): page_index
                    for page_index in range(max_pages)
                }
                for future in as_completed(future_to_page):
                    page_index = future_to_page[future]
                    try:
                        processed_page_index, page_payload, page_elapsed = future.result()
                    except Exception as exc:
                        raise RuntimeError(
                            f"PaddleOCR structured parse failed on {file_path.name} page {page_index + 1}/{max_pages}: {exc}"
                        ) from exc
                    logger.info(
                        "PaddleOCR structured parse processed %s page %s/%s in %.2fs at %s DPI (worker)",
                        file_path.name,
                        processed_page_index + 1,
                        max_pages,
                        page_elapsed,
                        effective_dpi,
                    )
                    page_payloads_by_index[processed_page_index] = page_payload
        else:
            ocr = _get_paddleocr(
                lang,
                cpu_threads,
                enable_mkldnn,
                det_limit_side_len,
                use_textline_orientation,
            )
            for page_index in range(max_pages):
                page = document.load_page(page_index)
                pixmap = page.get_pixmap(dpi=effective_dpi, colorspace=fitz.csRGB, alpha=False)
                image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                    pixmap.height,
                    pixmap.width,
                    3,
                )
                page_started_at = time.perf_counter()
                result = ocr.ocr(image, cls=False)
                page_elapsed = time.perf_counter() - page_started_at
                page_result = result[0] if isinstance(result, list) and len(result) == 1 else result
                logger.info(
                    "PaddleOCR structured parse processed %s page %s/%s in %.2fs at %s DPI",
                    file_path.name,
                    page_index + 1,
                    max_pages,
                    page_elapsed,
                    effective_dpi,
                )
                page_payloads_by_index[page_index] = {
                    "page_width": pixmap.width,
                    "page_height": pixmap.height,
                    "page_lines": _extract_page_lines(page_result),
                }

    for page_index in range(max_pages):
        payload = page_payloads_by_index.get(page_index, {})
        page_payload, paragraph_no_in_doc, global_line = _build_page_payload_from_ocr_lines(
            page_index=page_index + 1,
            hints=hints,
            page_width=int(payload.get("page_width") or 0),
            page_height=int(payload.get("page_height") or 0),
            page_lines=list(payload.get("page_lines") or []),
            paragraph_no_in_doc_start=paragraph_no_in_doc,
            global_line_start=global_line,
        )
        pages.append(page_payload)
        page_texts.append(str(page_payload.get("text") or ""))

    full_text = "\f".join(page_texts).strip()
    if not full_text:
        raise ValueError("PaddleOCR returned no text")

    return {
        "schema_version": 1,
        "source_filename": file_path.name,
        "title": title,
        "parser_name": parser_name,
        "hints": hints,
        "full_text": full_text,
        "pages": pages,
        "provider": "paddleocr_local",
    }


def extract_office_text_with_markitdown(file_path: Path) -> str | None:
    """Extract text from non-PDF office files via markitdown."""
    try:
        from markitdown import MarkItDown

        md = MarkItDown()
        result = md.convert(str(file_path))
        text = (result.text_content or "").strip()
        if not text:
            logger.warning("markitdown extracted empty text from %s", file_path.name)
            return None
        logger.info("markitdown extracted %s chars from %s", len(text), file_path.name)
        return text
    except Exception as exc:
        logger.exception("markitdown failed for %s: %s", file_path.name, exc)
        return None
