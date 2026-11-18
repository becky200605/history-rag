"""Read a book's outline from PDF bookmarks or printed contents pages."""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path
from typing import TypedDict

from src.community.knowledge_base.book_metadata import BookMetadataRecord

logger = logging.getLogger(__name__)

_CHAPTER = re.compile(r"第\s*[〇零一二三四五六七八九十百两兩\d]+\s*([编編篇卷章节節])")
_CONTENTS_HEADING = re.compile(r"(?m)^\s*(?:目\s*[录錄]|(?:table of )?contents)\s*$", re.IGNORECASE)
_PRINTED_PAGE = re.compile(r"(?:\(\s*(\d+)\s*\)|[.·…。\s]{2,}(\d+))\s*$")
_YEAR_RANGE = re.compile(r"\(\s*\d{4}\s*[-‐–—一至]\s*\d{4}\s*年?\s*\)")
_FRONT_PAGE_LIMIT = 12


class BookOutlineEntry(TypedDict):
    title: str
    level: int
    book_page_no: int | None
    pdf_page_no: int | None


def _read_printed_outline(pages: list[str]) -> list[BookOutlineEntry]:
    entries: list[BookOutlineEntry] = []
    found_heading = False
    for raw_page in pages:
        page = unicodedata.normalize("NFKC", raw_page)
        heading = _CONTENTS_HEADING.search(page)
        if heading:
            found_heading = True
            page = page[heading.end():]
        elif not found_heading:
            continue

        # OCR can put the next entry right after the previous entry's page number.
        page = re.sub(rf"(?<=\)){_CHAPTER.pattern}", lambda match: f"\n{match[0]}", page)
        page_entries: list[BookOutlineEntry] = []
        for line in page.splitlines():
            line = line.strip()
            chapter = _CHAPTER.match(line)
            if not chapter or len(line) > 180:
                continue
            page_match = _PRINTED_PAGE.search(line)
            page_no = int(page_match[1] or page_match[2]) if page_match else None
            title = line[:page_match.start()] if page_match else line
            title = title.rstrip(" .·…。").strip()
            title = f"{chapter[0]} {title[chapter.end():].strip()}".strip()
            page_entries.append({
                "title": title,
                "level": 2 if chapter[1] in "节節" else 1,
                "book_page_no": page_no,
                "pdf_page_no": None,
            })

        if any(entry["book_page_no"] for entry in page_entries):
            entries.extend(page_entries)
        elif entries:
            break

    return entries


def _chapter_key(title: str) -> str:
    title = _YEAR_RANGE.sub("", unicodedata.normalize("NFKC", title))
    return re.sub(r"[\W_]", "", title)


def _match_bookmarked_chapters(
    entries: list[BookOutlineEntry], bookmarks: list[BookOutlineEntry],
) -> dict[str, int] | None:
    """Use the printed hierarchy if it covers the chapters in the PDF bookmarks."""
    printed_chapters = {_chapter_key(entry["title"]) for entry in entries if entry["level"] == 1}
    if not any(entry["level"] > 1 for entry in entries):
        return None

    chapter_pages: dict[str, int] = {}
    for bookmark in bookmarks:
        key = _chapter_key(bookmark["title"])
        if key in {"封面", "目录", "目錄", "正文", "Cover", "Contents"}:
            continue
        match = _CHAPTER.match(bookmark["title"])
        if not match or match[1] in "节節":
            return None
        page = bookmark["pdf_page_no"]
        if key not in printed_chapters or page is None or key in chapter_pages:
            return None
        chapter_pages[key] = page
    return chapter_pages or None


def load_book_outline(source: Path, metadata: BookMetadataRecord | None) -> list[BookOutlineEntry]:
    entries = _read_printed_outline([page.text for page in metadata.prompt_input.selected_pages[:_FRONT_PAGE_LIMIT]]) if metadata else []
    if source.suffix.lower() != ".pdf" or not source.is_file():
        return entries

    try:
        import fitz

        with fitz.open(source) as document:
            bookmarks: list[BookOutlineEntry] = [
                {
                    "title": title.strip(),
                    "level": level,
                    "book_page_no": None,
                    "pdf_page_no": page if 1 <= page <= document.page_count else None,
                }
                for level, title, page in document.get_toc()
                if title.strip()
            ]
            if not entries:
                entries = _read_printed_outline([page.get_text() for page in document.pages(0, _FRONT_PAGE_LIMIT)])

            chapter_pages = _match_bookmarked_chapters(entries, bookmarks) if bookmarks else {}
            if chapter_pages is None:
                return bookmarks

            has_page_labels = bool(document.get_page_labels())
            for entry in entries:
                chapter_page = chapter_pages.get(_chapter_key(entry["title"])) if entry["level"] == 1 else None
                if chapter_page is not None:
                    entry["pdf_page_no"] = chapter_page
                    if has_page_labels and entry["book_page_no"] is None:
                        label = document[chapter_page - 1].get_label()
                        if label.isascii() and label.isdecimal() and document.get_page_numbers(label) == [chapter_page - 1]:
                            entry["book_page_no"] = int(label)
                elif has_page_labels and entry["book_page_no"] is not None:
                    matches = document.get_page_numbers(str(entry["book_page_no"]))
                    if len(matches) == 1:
                        entry["pdf_page_no"] = matches[0] + 1
    except (ImportError, OSError, RuntimeError, ValueError):
        logger.warning("Unable to read PDF outline for %s", source.name, exc_info=True)

    return entries
