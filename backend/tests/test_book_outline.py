import fitz

from src.community.knowledge_base.book_metadata import (
    BookMetadataPromptInput,
    BookMetadataRecord,
    BookMetadataSamplePage,
)
from src.community.knowledge_base.book_outline import load_book_outline


def test_printed_outline_reads_consecutive_contents_pages_without_guessing_pdf_pages(tmp_path):
    pages = [
        "封面",
        "目 录\n第一章 财政制度……（1）\n第一节 预算……（2）第二节 税收……（3）",
        "第二章 公债……（4）\n第一节 发行……（4）",
        "第一章 财政制度\n第一节 预算\n此处是正文。",
    ]
    filename = "财政史.pdf"
    metadata = BookMetadataRecord(
        source_filename=filename,
        source_title="财政史",
        page_count=len(pages),
        prompt_input=BookMetadataPromptInput(
            source_filename=filename,
            title="财政史",
            page_count=len(pages),
            selected_pages=[BookMetadataSamplePage(page_no=i, text=text) for i, text in enumerate(pages, 1)],
        ),
    )
    source = tmp_path / filename

    with fitz.open() as document:
        for _ in range(5):
            document.new_page()
        document.save(source)

    entries = load_book_outline(source, metadata)

    assert [entry["title"] for entry in entries] == ["第一章 财政制度", "第一节 预算", "第二节 税收", "第二章 公债", "第一节 发行"]
    assert [entry["level"] for entry in entries] == [1, 2, 2, 1, 2]
    assert [entry["book_page_no"] for entry in entries] == [1, 2, 3, 4, 4]
    assert all(entry["pdf_page_no"] is None for entry in entries)

    with fitz.open(source) as document:
        document.set_page_labels([{"startpage": 0, "prefix": "前置页-"}, {"startpage": 1, "style": "D"}])
        document.saveIncr()

    assert [entry["pdf_page_no"] for entry in load_book_outline(source, metadata)] == [2, 3, 4, 5, 5]


def test_pdf_bookmarks_keep_their_hierarchy_and_physical_page_numbers(tmp_path):
    source = tmp_path / "book.pdf"
    with fitz.open() as document:
        document.new_page()
        document.new_page()
        document.set_toc([[1, "第一章", 1], [2, "第一节", 2]])
        document.save(source)

    assert load_book_outline(source, None) == [
        {"title": "第一章", "level": 1, "book_page_no": None, "pdf_page_no": 1},
        {"title": "第一节", "level": 2, "book_page_no": None, "pdf_page_no": 2},
    ]


def test_chapter_bookmarks_and_page_labels_enrich_printed_sections(tmp_path):
    filename = "book.pdf"
    source = tmp_path / filename
    metadata = BookMetadataRecord(
        source_filename=filename,
        source_title="财政史",
        page_count=7,
        prompt_input=BookMetadataPromptInput(
            source_filename=filename,
            title="财政史",
            page_count=7,
            selected_pages=[BookMetadataSamplePage(
                page_no=2,
                text="目 录\n第一章 财政制度（1912—1927年）……（1）\n第一节 预算……（2）\n第二章 公债\n第一节 发行……（4）",
            )],
        ),
    )
    with fitz.open() as document:
        for _ in range(7):
            document.new_page()
        document.set_page_labels([{"startpage": 0, "style": "r"}, {"startpage": 2, "style": "D"}])
        document.set_toc([[1, "封面", 1], [1, "目录", 2], [1, "正文", 3], [2, "第一章 财政制度", 3], [2, "第二章 公债", 6]])
        document.save(source)

    entries = load_book_outline(source, metadata)
    assert [(entry["level"], entry["book_page_no"], entry["pdf_page_no"]) for entry in entries] == [
        (1, 1, 3), (2, 2, 4), (1, 4, 6), (2, 4, 6),
    ]
