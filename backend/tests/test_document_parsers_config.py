from src.community.knowledge_base.document_parsers import _resolve_local_pdf_ocr_runtime_options


def test_resolve_local_pdf_ocr_runtime_options_defaults(monkeypatch) -> None:
    for key in (
        "LOCAL_PDF_OCR_DPI",
        "LOCAL_PDF_OCR_CPU_THREADS",
        "LOCAL_PDF_OCR_ENABLE_MKLDNN",
        "LOCAL_PDF_OCR_DET_LIMIT_SIDE_LEN",
        "LOCAL_PDF_OCR_USE_TEXTLINE_ORIENTATION",
        "LOCAL_PDF_OCR_WORKERS",
    ):
        monkeypatch.delenv(key, raising=False)

    options = _resolve_local_pdf_ocr_runtime_options()

    assert options == {
        "dpi": 160,
        "cpu_threads": None,
        "enable_mkldnn": False,
        "det_limit_side_len": None,
        "use_textline_orientation": True,
        "workers": 1,
    }


def test_resolve_local_pdf_ocr_runtime_options_from_env(monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_PDF_OCR_DPI", "144")
    monkeypatch.setenv("LOCAL_PDF_OCR_CPU_THREADS", "4")
    monkeypatch.setenv("LOCAL_PDF_OCR_ENABLE_MKLDNN", "true")
    monkeypatch.setenv("LOCAL_PDF_OCR_DET_LIMIT_SIDE_LEN", "768")
    monkeypatch.setenv("LOCAL_PDF_OCR_USE_TEXTLINE_ORIENTATION", "false")
    monkeypatch.setenv("LOCAL_PDF_OCR_WORKERS", "2")

    options = _resolve_local_pdf_ocr_runtime_options()

    assert options == {
        "dpi": 144,
        "cpu_threads": 4,
        "enable_mkldnn": True,
        "det_limit_side_len": 768,
        "use_textline_orientation": False,
        "workers": 2,
    }
