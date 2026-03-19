from src.community.knowledge_base.mineru_grpc import build_structured_document_from_mineru_response
from src.community.knowledge_base.mineru_proto import mineru_pb2


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
    assert payload["pages"][0]["page_no"] is None
    assert payload["pages"][1]["pdf_page_no"] == 2
    assert payload["pages"][1]["page_no"] == 1


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
