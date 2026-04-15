from pathlib import Path

from pypdf import PdfReader, PdfWriter

from src.community.knowledge_base.mineru_grpc import (
    build_structured_document_from_mineru_grpc,
    build_structured_document_from_mineru_response,
)
from src.community.knowledge_base.mineru_proto import mineru_pb2
from src.config.knowledge_base_config import MineruConfig


def test_build_structured_document_from_mineru_response_with_full_text() -> None:
    response = mineru_pb2.ParsePdfResponse(
        task_id="task-1",
        document=mineru_pb2.StructuredDocument(
            full_text="第一页第一段\n\n第一页第二段\f第二页第一段",
        ),
    )

    payload = build_structured_document_from_mineru_response(
        source_filename="demo.pdf",
        title="Demo",
        parser_name="ocr_pdf_mineru_grpc",
        response=response,
        hints={"book_page_start_pdf_page": "2", "book_page_start_value": "1"},
    )

    assert payload["provider"] == "mineru_grpc"
    assert payload["provider_result_meta"] == {"task_id": "task-1"}
    assert payload["pages"][0]["pdf_page_no"] == 1
    assert payload["pages"][0]["page_no"] == 1
    assert payload["pages"][0]["book_page_no"] == 1
    assert payload["pages"][1]["pdf_page_no"] == 2
    assert payload["pages"][1]["page_no"] == 2
    assert payload["pages"][1]["book_page_no"] == 2


def test_build_structured_document_from_mineru_response_with_pages() -> None:
    response = mineru_pb2.ParsePdfResponse(
        document=mineru_pb2.StructuredDocument(
            pages=[
                mineru_pb2.Page(
                    pdf_page_no=3,
                    paragraphs=[
                        mineru_pb2.Paragraph(
                            text="第一段",
                            bbox=mineru_pb2.BBox(x=10, y=20, width=100, height=40),
                        ),
                        mineru_pb2.Paragraph(
                            text="第二段",
                            line_start=5,
                            line_end=6,
                        ),
                    ],
                )
            ]
        )
    )

    payload = build_structured_document_from_mineru_response(
        source_filename="demo.pdf",
        title="Demo",
        parser_name="ocr_pdf_mineru_grpc",
        response=response,
        hints=None,
    )

    assert payload["provider"] == "mineru_grpc"
    assert payload["pages"][0]["pdf_page_no"] == 3
    assert payload["pages"][0]["paragraphs"][0]["bbox"]["x"] == 10.0
    assert payload["pages"][0]["paragraphs"][0]["bbox_source"] == "mineru_grpc"
    assert payload["pages"][0]["paragraphs"][1]["paragraph_no"] == 2


def test_build_structured_document_from_mineru_response_without_proto_paragraphs_keeps_single_page_paragraph() -> None:
    response = mineru_pb2.ParsePdfResponse(
        document=mineru_pb2.StructuredDocument(
            pages=[
                mineru_pb2.Page(
                    pdf_page_no=7,
                    text="第一行\n\n第二行\n第三行",
                )
            ]
        )
    )

    payload = build_structured_document_from_mineru_response(
        source_filename="demo.pdf",
        title="Demo",
        parser_name="ocr_pdf_mineru_grpc",
        response=response,
        hints=None,
    )

    paragraphs = payload["pages"][0]["paragraphs"]
    assert len(paragraphs) == 1
    assert paragraphs[0]["text"] == "第一行\n\n第二行\n第三行"
    assert paragraphs[0]["line_start"] == 1
    assert paragraphs[0]["line_end"] == 4


def test_build_structured_document_from_mineru_grpc_auto_splits_large_pdf(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "big.pdf"
    writer = PdfWriter()
    for _ in range(5):
        writer.add_blank_page(width=72, height=72)
    with pdf_path.open("wb") as handle:
        writer.write(handle)

    config = MineruConfig(
        enabled=True,
        target="mineru.internal:50051",
        pdf_split_page_threshold=2,
        pdf_chunk_page_count=2,
        pdf_split_size_threshold_bytes=1,
    )
    monkeypatch.setattr(
        "src.community.knowledge_base.mineru_grpc._get_mineru_config",
        lambda: config,
    )

    def fake_parse_pdf_response(file_path: Path, **_: object) -> mineru_pb2.ParsePdfResponse:
        chunk_reader = PdfReader(str(file_path))
        return mineru_pb2.ParsePdfResponse(
            task_id=file_path.stem,
            document=mineru_pb2.StructuredDocument(
                pages=[
                    mineru_pb2.Page(
                        pdf_page_no=page_index,
                        text=f"{file_path.stem}-page-{page_index}",
                    )
                    for page_index in range(1, len(chunk_reader.pages) + 1)
                ]
            ),
        )

    monkeypatch.setattr(
        "src.community.knowledge_base.mineru_grpc._parse_pdf_response_via_mineru_grpc",
        fake_parse_pdf_response,
    )

    payload = build_structured_document_from_mineru_grpc(
        pdf_path,
        title="Big PDF",
        parser_name="ocr_pdf_mineru_grpc",
    )

    assert payload["provider"] == "mineru_grpc"
    assert payload["provider_result_meta"]["chunked"] is True
    assert payload["provider_result_meta"]["chunk_count"] == 3
    assert payload["provider_result_meta"]["total_pages"] == 5
    assert payload["provider_result_meta"]["chunk_ranges"] == [
        {"start_pdf_page": 1, "end_pdf_page": 2},
        {"start_pdf_page": 3, "end_pdf_page": 4},
        {"start_pdf_page": 5, "end_pdf_page": 5},
    ]
    assert [page["pdf_page_no"] for page in payload["pages"]] == [1, 2, 3, 4, 5]
    assert payload["pages"][4]["paragraphs"][0]["paragraph_id"] == "page-5-p1"
    assert payload["pages"][4]["paragraphs"][0]["paragraph_no_in_doc"] == 5
