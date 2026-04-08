from __future__ import annotations

from typing import Any, Generic, TYPE_CHECKING, TypeVar
try:
    from langchain.tools import ToolRuntime, tool
except ImportError:  # pragma: no cover - compatibility with older LangChain layouts
    from langchain.tools import tool

    _ToolRuntimeContextT = TypeVar("_ToolRuntimeContextT")
    _ToolRuntimeStateT = TypeVar("_ToolRuntimeStateT")

    class ToolRuntime(Generic[_ToolRuntimeContextT, _ToolRuntimeStateT]):  # type: ignore[no-redef]
        pass
try:
    from langgraph.typing import ContextT
except ImportError:  # pragma: no cover - compatibility with older LangGraph layouts
    ContextT = TypeVar("ContextT")

if TYPE_CHECKING:
    from src.agents.thread_state import ThreadState
else:  # pragma: no cover - runtime fallback for import-light utility modules
    ThreadState = Any  # type: ignore[assignment]
from src.community.knowledge_base.catalog import (
    CORE_TYPE,
    REFERENCE_TYPE,
    SPECIALIZED_TYPE,
    BookCatalogEntry,
    search_book_catalog,
)
from src.community.knowledge_base.citations import resolve_result_citation_context
from src.community.knowledge_base.locator import extract_document_context, locate_document

BOOK_SEARCH_TOP_K = 20
KNOWLEDGE_SEARCH_TOP_K = 6
KNOWLEDGE_RESULT_MAX_CHARS = 900
KNOWLEDGE_RESULT_MAX_LINES = 24
ALLOWED_SEARCH_SCOPES = {"user", "thread", "global"}


def _parse_doc_ids(doc_ids: str | None) -> list[str] | None:
    if not doc_ids:
        return None
    parsed = [item.strip() for item in doc_ids.split(",") if item.strip()]
    return parsed or None


def _parse_scopes(scopes: str | None) -> list[str] | None:
    if not scopes:
        return None
    parsed = []
    seen: set[str] = set()
    for item in scopes.split(","):
        normalized = item.strip().lower()
        if not normalized or normalized not in ALLOWED_SEARCH_SCOPES or normalized in seen:
            continue
        seen.add(normalized)
        parsed.append(normalized)
    return parsed or None


def _build_location_text(
    *,
    page: int | None = None,
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
    if page is not None:
        return f"PDF 第 {page + 1} 页"
    return None


def _build_citation_label(
    title: str,
    page_no: int | None,
    pdf_page_no: int | None,
    paragraph_no: int | None,
    page: int | None = None,
) -> str:
    parts = [title]
    location = _build_location_text(
        page=page,
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


def _normalize_type(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"user", "thread", CORE_TYPE, SPECIALIZED_TYPE, REFERENCE_TYPE}:
        return normalized
    return "unknown"


def _format_book_metadata(candidate: BookCatalogEntry) -> str:
    parts: list[str] = []
    book_type = _normalize_type(candidate.type)
    if book_type != "unknown":
        parts.append(f"类型: {book_type}")
    if candidate.categories:
        parts.append(f"分类: {'、'.join(candidate.categories)}")
    if candidate.eras:
        parts.append(f"时代: {'、'.join(candidate.eras)}")
    if candidate.regions:
        parts.append(f"地区: {'、'.join(candidate.regions)}")
    if candidate.priority is not None:
        parts.append(f"优先级: {candidate.priority}")
    if candidate.score is not None:
        parts.append(f"相关度: {candidate.score:.2f}")
    if candidate.summary:
        parts.append(f"摘要: {candidate.summary}")
    return " | ".join(parts)


def _group_book_candidates(candidates: list[BookCatalogEntry]) -> dict[str, list[BookCatalogEntry]]:
    grouped = {
        "user": [],
        "thread": [],
        CORE_TYPE: [],
        SPECIALIZED_TYPE: [],
        REFERENCE_TYPE: [],
        "unknown": [],
    }
    for candidate in candidates:
        candidate_key = "user" if candidate.scope == "user" else "thread" if candidate.scope == "thread" else _normalize_type(candidate.type)
        grouped.setdefault(candidate_key, grouped["unknown"]).append(candidate)
    return grouped


@tool("book_search", parse_docstring=True)
def book_search_tool(runtime: ToolRuntime[ContextT, ThreadState], query: str) -> str:
    """Search candidate books before full-text retrieval.

    Use this tool first for historical/domain questions. It finds likely user
    books and system books before full-text retrieval so the agent can search
    in a layered order instead of jumping directly into the whole corpus.

    Args:
        query: The user's research question or topic description.
    """
    thread_id = runtime.context.get("thread_id")
    user_id = runtime.context.get("user_id")
    candidates = search_book_catalog(query, thread_id=thread_id, user_id=user_id, top_k=BOOK_SEARCH_TOP_K)
    if not candidates:
        return "No likely books found for this query."

    grouped = _group_book_candidates(candidates)
    lines = ["## 候选书目", ""]
    section_titles = (
        ("user", "用户书籍"),
        ("thread", "当前线程书籍"),
        (CORE_TYPE, "核心通用书"),
        (SPECIALIZED_TYPE, "专题支撑书"),
        (REFERENCE_TYPE, "补充材料 / 参考工具书"),
        ("unknown", "其他候选书"),
    )
    for role, title in section_titles:
        items = grouped.get(role, [])
        if not items:
            continue
        lines.append(f"### {title}")
        for index, candidate in enumerate(items, 1):
            lines.append(f"#### 书目 {index}: {candidate.title}")
            lines.append(f"doc_id: {candidate.doc_id}")
            lines.append(f"范围: {candidate.scope}")
            metadata_text = _format_book_metadata(candidate)
            if metadata_text:
                lines.append(metadata_text)
            lines.append("")

    user_doc_ids = ", ".join(candidate.doc_id for candidate in grouped["user"])
    thread_doc_ids = ", ".join(candidate.doc_id for candidate in grouped["thread"])
    core_doc_ids = ", ".join(candidate.doc_id for candidate in grouped[CORE_TYPE])
    specialized_doc_ids = ", ".join(candidate.doc_id for candidate in grouped[SPECIALIZED_TYPE])
    reference_doc_ids = ", ".join(candidate.doc_id for candidate in grouped[REFERENCE_TYPE])
    all_doc_ids = ", ".join(candidate.doc_id for candidate in candidates)

    lines.append("---")
    lines.append("推荐链路:")
    lines.append("1. 先做书目分层，不要跳过 `book_search` 直接整库检索。")
    lines.append("2. 在每一层内部，优先把该层相关 `doc_ids` 一起传给 `knowledge_search` 做一轮批量检索，先看这一层里每本书分别贡献了什么。")
    lines.append("3. 先检索 `用户书籍`；如果当前线程有相关上传，也并行参考 `当前线程书籍`。")
    lines.append("4. 再检索系统层的 `核心通用书`，先建立稳固的总体框架。")
    lines.append("5. 如果核心通用书仍不足，再扩展到 `专题支撑书`。")
    lines.append("6. `补充材料 / 参考工具书` 作为最后补强层，用来补细节、对照和查缺。")
    lines.append("7. 批量检索之后，再对命中较好的书逐本深挖；不要只读到一本就停止。")
    lines.append("8. 回答前要整合不同层级、不同书籍里的证据，不要只抓单个综述段落，也不要让单本书主导全部结论。")
    lines.append("9. 如果搜到的大多是目录、标题、页眉页脚、边栏或过短片段，不要急着作答，把它们当作导航线索，继续搜目录/章节名/阶段名，并配合 `knowledge_locate` 展开正文。")
    lines.append("10. 默认假设关键信息是散落的：散落在很多书里，也散落在同一本书的不同章节、不同段落里，所以往往需要检索一本书的很多地方才能形成用户满意的回答。")
    lines.append("11. 在真正作答前，先检查：现在的资料是否已经覆盖了问题的每个主要部分？每个部分是否都有足够的实质证据？如果还没有，就继续检索，不要急着回答。")
    if user_doc_ids:
        lines.append(f"user doc_ids: {user_doc_ids}")
    if thread_doc_ids:
        lines.append(f"thread doc_ids: {thread_doc_ids}")
    if core_doc_ids:
        lines.append(f"core doc_ids: {core_doc_ids}")
    if specialized_doc_ids:
        lines.append(f"specialized doc_ids: {specialized_doc_ids}")
    if reference_doc_ids:
        lines.append(f"reference doc_ids: {reference_doc_ids}")
    lines.append(f"all doc_ids: {all_doc_ids}")
    return "\n".join(lines)


@tool("knowledge_search", parse_docstring=True)
def knowledge_search_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    query: str,
    doc_ids: str | None = None,
    scopes: str | None = None,
) -> str:
    """Search the internal knowledge base for domain-specific information.

    This tool should usually be used after `book_search`, so retrieval can
    focus on the right books in a layered order instead of jumping into the
    whole corpus. For broad history questions, it also expands the query into
    multiple investigative facets so scattered records can be gathered and
    synthesized together.

    Recommended use:
    1. First call `book_search(query=...)` to identify likely user/system books.
    2. Then call `knowledge_search` against the selected layer of books.
       Inside one layer, prefer passing multiple relevant `doc_ids` together for
       a first-pass batch search, instead of reading only one book first.
    3. After the batch pass, continue with narrower per-book queries and
       `knowledge_locate` on the books/locations that look promising.
    4. For exact quotation / page / paragraph lookups, you may use narrower
       scopes or doc filters and then call `knowledge_locate` for nearby context.

    This tool searches through curated internal documents and returns relevant
    knowledge snippets with source document references.

    Args:
        query: The search query describing what information you need.
        doc_ids: Optional comma-separated candidate book IDs from `book_search`.
        scopes: Optional comma-separated scopes: `user`, `thread`, `global`.
    """
    try:
        from src.community.knowledge_base.retriever import get_retriever

        retriever = get_retriever()
        parsed_doc_ids = _parse_doc_ids(doc_ids)
        parsed_scopes = _parse_scopes(scopes)
        results = retriever.search(
            query,
            thread_id=runtime.context.get("thread_id"),
            user_id=runtime.context.get("user_id"),
            doc_ids=parsed_doc_ids,
            scopes=parsed_scopes,
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
        matched_queries = [str(item) for item in result.get("matched_queries") or [] if str(item).strip()]
        citation_context = resolve_result_citation_context(
            result,
            thread_id=runtime.context.get("thread_id"),
            user_id=runtime.context.get("user_id"),
        )
        source_url = citation_context["source_url"]
        citation_url = citation_context.get("citation_url")
        citation_label = _build_citation_label(
            str(citation_context["citation_title"] or title),
            citation_context["citation_page_no"],
            citation_context["citation_pdf_page_no"],
            citation_context["citation_paragraph_no"],
            page=citation_context["citation_page"],
        )
        citation = _build_citation(citation_label, citation_url or source_url)

        formatted_output += f"### 来源 {i}: {title} - 相关度: {score:.2f}\n"
        if doc_id:
            formatted_output += f"doc_id: {doc_id}\n"
        if matched_queries:
            formatted_output += f"命中分面: {'、'.join(matched_queries)}\n"
        if citation_context.get("source_label") and citation_context.get("source_scope") in {"user", "thread"}:
            formatted_output += f"来源类型: {citation_context['source_label']}\n"
        if (
            citation_context.get("source_scope") == "user"
            and citation_context.get("original_title")
            and citation_context.get("original_title") != title
        ):
            formatted_output += f"原文来源: {citation_context['original_title']}\n"
        if citation:
            formatted_output += f"citation: {citation}\n"

        location = _build_location_text(
            page=citation_context["citation_page"],
            page_no=citation_context["citation_page_no"],
            pdf_page_no=citation_context["citation_pdf_page_no"],
            paragraph_no=citation_context["citation_paragraph_no"],
        )
        if location:
            formatted_output += f"定位: {location}\n"
        if line_start and line_end:
            formatted_output += f"定位: 第 {line_start}-{line_end} 行\n"
        elif line_start:
            formatted_output += f"定位: 第 {line_start} 行\n"
        formatted_output += f"{content}\n\n"

    formatted_output += "---\n"
    formatted_output += "这些结果已经做过联合检索与分面扩展；回答前先归并不同来源里的分散证据，不要只摘取单个综述段落。\n"
    formatted_output += "如果某条结果看起来像目录、标题、页眉页脚、边栏、图表标题或过短片段，把它当作导航线索，不要直接拿来支撑最终结论。\n"
    formatted_output += "遇到这类线索时，继续搜索对应的目录词、章节名、阶段名、制度名，再调用 `knowledge_locate` 展开附近正文。\n"
    formatted_output += "使用答案时，直接复制上面的 `citation:` 行，不要自己重写。\n"
    formatted_output += "如果需要更多上下文，调用 `knowledge_locate`；不要去读原始 PDF 或 `.structured.json`。\n"
    formatted_output += "如果证据不足，使用 `【无法回答】` 开头直接拒答，并简要说明当前资料范围内没有足够依据。"

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
        document = locate_document(
            runtime.context.get("thread_id"),
            user_id=runtime.context.get("user_id"),
            doc_id=doc_id,
            filename=filename,
        )
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
    lines.append(
        "IMPORTANT: Use these excerpts as the follow-up source context. "
        "Do not inspect raw PDFs or `.structured.json` files directly."
    )
    return "\n".join(lines)
