from urllib.parse import quote, urlencode

from langchain.tools import ToolRuntime, tool
from langgraph.typing import ContextT

from src.community.knowledge_base.catalog import search_book_catalog
from src.community.knowledge_base.locator import extract_document_context, locate_document
from src.community.knowledge_base.retriever import get_retriever
from src.agents.thread_state import ThreadState

BOOK_SEARCH_TOP_K = 5
KNOWLEDGE_SEARCH_TOP_K = 3
KNOWLEDGE_RESULT_MAX_CHARS = 900
KNOWLEDGE_RESULT_MAX_LINES = 24


def _parse_doc_ids(doc_ids: str | None) -> list[str] | None:
    if not doc_ids:
        return None
    parsed = [item.strip() for item in doc_ids.split(",") if item.strip()]
    return parsed or None


def _encode_source_url(url: str | None) -> str | None:
    if not url:
        return url
    return quote(url, safe="/:?=&%#")


def _append_pdf_page_fragment(url: str | None, pdf_page_no: int | None) -> str | None:
    if not url or not pdf_page_no or "#page=" in url:
        return url
    return f"{url}#page={pdf_page_no}"


def _append_location_params(
    url: str | None,
    *,
    page_no: int | None = None,
    pdf_page_no: int | None = None,
    paragraph_no: int | None = None,
) -> str | None:
    if not url:
        return url
    base, sep, fragment = url.partition("#")
    params: dict[str, int] = {}
    if page_no:
        params["page_no"] = page_no
    if pdf_page_no:
        params["pdf_page_no"] = pdf_page_no
    if paragraph_no:
        params["paragraph_no"] = paragraph_no
    if params:
        joiner = "&" if "?" in base else "?"
        base = f"{base}{joiner}{urlencode(params)}"
    if sep:
        return f"{base}#{fragment}"
    return base


def _build_location_text(
    *,
    page_no: int | None,
    pdf_page_no: int | None,
    paragraph_no: int | None,
) -> str | None:
    if page_no:
        location = f"原书第 {page_no} 页"
        if paragraph_no:
            location += f" 第 {paragraph_no} 段"
        if pdf_page_no and pdf_page_no != page_no:
            location += f"（PDF 第 {pdf_page_no} 页）"
        return location
    if pdf_page_no:
        location = f"PDF 第 {pdf_page_no} 页"
        if paragraph_no:
            location += f" 第 {paragraph_no} 段"
        return location
    return None


def _build_citation_label(
    title: str,
    page_no: int | None,
    pdf_page_no: int | None,
    paragraph_no: int | None,
) -> str:
    parts = [title]
    location = _build_location_text(
        page_no=page_no,
        pdf_page_no=pdf_page_no,
        paragraph_no=paragraph_no,
    )
    if location:
        location = location.replace(" ", "")
        parts.append(location)
    return " ".join(parts)


def _build_citation(citation_label: str, citation_link: str | None) -> str | None:
    if not citation_link:
        return None
    return f"[citation:{citation_label}]({citation_link})"


def _truncate_text(text: str, *, max_chars: int, max_lines: int | None = None) -> str:
    normalized = text.strip()
    if not normalized:
        return normalized

    if max_lines is not None:
        lines = normalized.splitlines()
        if len(lines) > max_lines:
            normalized = "\n".join(lines[:max_lines]).rstrip() + "\n..."

    if len(normalized) > max_chars:
        normalized = normalized[: max_chars - 3].rstrip() + "..."

    return normalized


@tool("book_search", parse_docstring=True)
def book_search_tool(runtime: ToolRuntime[ContextT, ThreadState], query: str) -> str:
    """Search candidate books before full-text retrieval.

    Use this tool first when the corpus is large or when you need to narrow the
    search to a smaller set of likely relevant books before calling `knowledge_search`.

    Args:
        query: The user's research question or topic description.
    """
    thread_id = runtime.context.get("thread_id")
    candidates = search_book_catalog(query, thread_id=thread_id, top_k=BOOK_SEARCH_TOP_K)
    if not candidates:
        return "No likely books found for this query."

    lines = ["## 候选书目", ""]
    for index, candidate in enumerate(candidates, 1):
        lines.append(f"### 书目 {index}: {candidate.title}")
        lines.append(f"doc_id: {candidate.doc_id}")
        lines.append(f"范围: {candidate.scope}")
        lines.append("")

    doc_ids = ", ".join(candidate.doc_id for candidate in candidates)
    lines.append("---")
    lines.append("如果这些候选书看起来相关，下一步调用 `knowledge_search`，并传入下面这串 doc_ids：")
    lines.append(doc_ids)
    return "\n".join(lines)


@tool("knowledge_search", parse_docstring=True)
def knowledge_search_tool(runtime: ToolRuntime[ContextT, ThreadState], query: str, doc_ids: str | None = None) -> str:
    """Search the internal knowledge base for domain-specific information.

    Use this tool when the user asks questions about specialized domain knowledge,
    internal company information, or topics covered in the knowledge base.
    
    This tool searches through curated internal documents and returns relevant
    knowledge snippets with source document references.

    Args:
        query: The search query describing what information you need.
        doc_ids: Optional comma-separated candidate book IDs from `book_search`.
    """
    try:
        retriever = get_retriever()
        parsed_doc_ids = _parse_doc_ids(doc_ids)
        results = retriever.search(
            query,
            thread_id=runtime.context.get("thread_id"),
            doc_ids=parsed_doc_ids,
        )
    except Exception as e:
        return f"Error searching knowledge base: {e}"

    if not results:
        return "No relevant information found in the knowledge base."

    formatted_output = "## 检索结果\n\n"

    for i, result in enumerate(results[:KNOWLEDGE_SEARCH_TOP_K], 1):
        content = _truncate_text(
            result["content"],
            max_chars=KNOWLEDGE_RESULT_MAX_CHARS,
            max_lines=KNOWLEDGE_RESULT_MAX_LINES,
        )
        filename = result.get("filename", "Unknown")
        score = result.get("score", 0.0)
        metadata = result.get("metadata", {})
        title = metadata.get("title") or filename
        doc_id = metadata.get("doc_id")
        line_start = metadata.get("line_start")
        line_end = metadata.get("line_end")
        page_no = metadata.get("page_no")
        pdf_page_no = metadata.get("pdf_page_no")
        paragraph_no = metadata.get("paragraph_no")
        scope = metadata.get("scope", "global")
        if scope == "thread":
            thread_id = metadata.get("thread_id") or runtime.context.get("thread_id")
            source_virtual_path = metadata.get("source_virtual_path", f"/mnt/user-data/uploads/{filename}")
            source_url = (
                f"/api/threads/{thread_id}/artifacts{source_virtual_path}"
                if thread_id
                else source_virtual_path
            )
            original_virtual_path = metadata.get("origin_virtual_path")
            original_url = (
                f"/api/threads/{thread_id}/artifacts{original_virtual_path}"
                if thread_id and original_virtual_path
                else original_virtual_path
            )
        else:
            source_url = f"/api/knowledge/docs/{filename}"
            origin_filename = metadata.get("origin_filename")
            original_url = f"/api/knowledge/docs/{origin_filename}" if origin_filename else None
        source_url = _append_pdf_page_fragment(source_url, pdf_page_no)
        original_url = _append_pdf_page_fragment(original_url, pdf_page_no)
        source_url = _append_location_params(
            source_url,
            page_no=page_no,
            pdf_page_no=pdf_page_no,
            paragraph_no=paragraph_no,
        )
        original_url = _append_location_params(
            original_url,
            page_no=page_no,
            pdf_page_no=pdf_page_no,
            paragraph_no=paragraph_no,
        )
        source_url = _encode_source_url(source_url)
        original_url = _encode_source_url(original_url)
        citation_label = _build_citation_label(title, page_no, pdf_page_no, paragraph_no)
        citation = _build_citation(citation_label, original_url or source_url)

        # Format the output for the agent
        formatted_output += f"### 来源 {i}: {title} - 相关度: {score:.2f}\n"
        if doc_id:
            formatted_output += f"doc_id: {doc_id}\n"
        if citation:
            formatted_output += f"citation: {citation}\n"
        location = _build_location_text(
            page_no=page_no,
            pdf_page_no=pdf_page_no,
            paragraph_no=paragraph_no,
        )
        if location:
            formatted_output += f"定位: {location}\n"
        if line_start and line_end:
            formatted_output += f"定位: 第 {line_start}-{line_end} 行\n"
        elif line_start:
            formatted_output += f"定位: 第 {line_start} 行\n"
        formatted_output += f"{content}\n"
        formatted_output += "\n"

    formatted_output += "---\n"
    formatted_output += "使用答案时，直接复制上面的 `citation:` 行，不要自己重写。\n"
    formatted_output += "如果需要更多上下文，调用 `knowledge_locate`；不要去读原始 PDF 或 `.structured.json`。\n"
    formatted_output += "如果证据不足，直接拒答，并说明当前资料范围内没有足够依据。"

    return formatted_output


@tool("knowledge_locate", parse_docstring=True)
def knowledge_locate_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    doc_id: str | None = None,
    filename: str | None = None,
    page_no: int | None = None,
    pdf_page_no: int | None = None,
    paragraph_no: int | None = None,
    line_start: int | None = None,
    line_end: int | None = None,
    window: int = 1,
) -> str:
    """Locate exact nearby source context from a known document and location.

    Use this after `knowledge_search` when you already know the relevant `doc_id`
    and need the nearby paragraphs around a cited page, paragraph, or line range.

    Args:
        doc_id: Optional document ID returned by `book_search` or `knowledge_search`.
        filename: Optional source filename if doc_id is unavailable.
        page_no: Optional page number to inspect.
        pdf_page_no: Optional physical PDF page number to inspect.
        paragraph_no: Optional paragraph number to inspect.
        line_start: Optional starting line number to inspect.
        line_end: Optional ending line number to inspect.
        window: Number of nearby paragraphs to include on each side.
    """
    if not doc_id and not filename:
        return "knowledge_locate requires either doc_id or filename."

    try:
        document = locate_document(runtime.context.get("thread_id"), doc_id=doc_id, filename=filename)
    except Exception as e:
        return f"Error locating document: {e}"
    if not document:
        return "No structured document found for the requested doc_id or filename."

    try:
        excerpts = extract_document_context(
            payload=document.payload,
            page_no=page_no,
            pdf_page_no=pdf_page_no,
            paragraph_no=paragraph_no,
            line_start=line_start,
            line_end=line_end,
            window=max(0, min(window, 5)),
        )
    except Exception as e:
        return f"Error extracting source context: {e}"

    if not excerpts:
        return "No matching page/paragraph/line context found in the structured document."

    lines = ["## 原文定位结果", ""]
    lines.append(f"标题: {document.title}")
    lines.append(f"doc_id: {document.doc_id}")
    lines.append(f"文件: {document.filename}")
    lines.append(f"范围: {document.scope}")
    lines.append(f"文档链接: {document.source_url}")
    if document.original_url and document.original_url != document.source_url:
        lines.append(f"原始文件: {document.original_url}")
    lines.append("")

    for index, excerpt in enumerate(excerpts, 1):
        location_text = _build_location_text(
            page_no=excerpt.get("page_no"),
            pdf_page_no=excerpt.get("pdf_page_no"),
            paragraph_no=excerpt.get("paragraph_no"),
        ) or "未标注页码"
        lines.append(f"### 片段 {index}: {location_text}")
        if excerpt.get("line_start") and excerpt.get("line_end"):
            lines.append(f"行号: {excerpt['line_start']}-{excerpt['line_end']}")
        elif excerpt.get("line_start"):
            lines.append(f"行号: {excerpt['line_start']}")
        lines.append(str(excerpt.get("text") or "").strip())
        lines.append("")

    lines.append("---")
    lines.append("IMPORTANT: Use these excerpts as the follow-up source context. Do not inspect raw PDFs or `.structured.json` files directly.")
    return "\n".join(lines)
