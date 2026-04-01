import sys
from types import ModuleType, SimpleNamespace

from src.community.knowledge_base.book_metadata import load_book_metadata_for_source
from src.community.knowledge_base.book_metadata_runtime import generate_book_metadata_record, maybe_generate_book_metadata
from src.config.knowledge_base_config import BookMetadataConfig


class _FakeModel:
    def __init__(self, response_text: str) -> None:
        self._response_text = response_text

    def invoke(self, messages):
        return SimpleNamespace(content=self._response_text)


def _structured_payload() -> dict[str, object]:
    pages = []
    for page_no in range(1, 13):
        text = f"第 {page_no} 页内容"
        if page_no == 3:
            text = "目录\n第一章 绪论 .......... 1\n第二章 财政 .......... 12"
        pages.append(
            {
                "page_no": page_no,
                "pdf_page_no": page_no,
                "book_page_no": page_no,
                "text": text,
                "paragraphs": [{"text": text}],
            }
        )
    return {
        "source_filename": "demo.pdf",
        "title": "Demo Book",
        "pages": pages,
    }


def test_generate_book_metadata_record_persists_model_output(monkeypatch, tmp_path) -> None:
    response_text = """
```json
{
  "title": "Demo Book",
  "type": {"value": "core", "confidence": 0.9, "evidence": "目录和前言"},
  "categories": [{"value": "财政史", "confidence": 0.8, "evidence": "目录"}],
  "summary": {"value": "财政通史著作", "confidence": 0.7, "evidence": "样本文本"}
}
```
""".strip()
    fake_models = ModuleType("src.models")
    fake_models.create_chat_model = lambda name=None, thinking_enabled=False: _FakeModel(response_text)
    monkeypatch.setitem(sys.modules, "src.models", fake_models)

    record, saved_path = generate_book_metadata_record(
        structured_payload=_structured_payload(),
        source_filename="demo.pdf",
        title="Demo Book",
        output_dir=tmp_path,
        config=BookMetadataConfig(enabled=True, model_name="demo-model"),
    )

    assert saved_path.exists()
    assert record.suggestion is not None
    assert record.suggestion.type is not None
    assert record.suggestion.type.value == "core"
    loaded = load_book_metadata_for_source(tmp_path, "demo.pdf")
    assert loaded is not None
    assert loaded.model_name == "demo-model"


def test_maybe_generate_book_metadata_returns_none_when_disabled(tmp_path) -> None:
    result = maybe_generate_book_metadata(
        structured_payload=_structured_payload(),
        source_filename="demo.pdf",
        title="Demo Book",
        output_dir=tmp_path,
        config=BookMetadataConfig(enabled=False),
    )
    assert result is None
