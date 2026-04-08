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
    list_book_catalog,
    search_book_catalog,
)
from src.community.knowledge_base.citations import resolve_result_citation_context
from src.community.knowledge_base.locator import extract_document_context, locate_document

BOOK_SEARCH_TOP_K = 20
KNOWLEDGE_SEARCH_TOP_K = 6
KNOWLEDGE_RESULT_MAX_CHARS = 900
KNOWLEDGE_RESULT_MAX_LINES = 24
ALLOWED_SEARCH_SCOPES = {"user", "thread", "global"}
SEARCH_SCOPE_ORDER = ("user", "thread", "global")
HISTORICAL_PERIOD_ALIASES = {
    "清代末期": ("晚清", "清末"),
    "晚清": ("清代末期", "清末"),
    "清末": ("晚清", "清代末期"),
    "民国时期": ("民国",),
    "民国": ("民国时期",),
}
HISTORICAL_TOPIC_RETRY_HINTS = ("情况", "概况", "变化", "变迁", "问题", "状况")
FINANCE_RETRY_FACETS = ("财政收入结构", "财政支出结构", "财政政策")


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


def _normalize_retry_query(query: str) -> str:
    return " ".join(query.split()).strip()


def _expand_period_alias_queries(query: str) -> list[str]:
    aliases: list[str] = []
    for period, replacements in HISTORICAL_PERIOD_ALIASES.items():
        if period not in query:
            continue
        for replacement in replacements:
            candidate = _normalize_retry_query(query.replace(period, replacement, 1))
            if candidate and candidate not in aliases:
                aliases.append(candidate)
    return aliases


def _rewrite_finance_retry_query(query: str, facet: str) -> str:
    import re

    return _normalize_retry_query(
        re.sub(
            r"财政(?:情况|概况|变化|变迁|问题|状况|体制|制度)?",
            facet,
            query,
            count=1,
        )
    )


def _build_retry_query_suggestions(query: str) -> list[str]:
    normalized = _normalize_retry_query(query)
    if not normalized:
        return []

    suggestions: list[str] = []

    def add_suggestion(candidate: str) -> None:
        if candidate and candidate not in suggestions:
            suggestions.append(candidate)

    alias_queries = _expand_period_alias_queries(normalized)
    for alias_query in alias_queries:
        add_suggestion(f"{alias_query}如何")

    base_query = alias_queries[0] if alias_queries else normalized
    if "财政" in normalized and any(hint in normalized for hint in HISTORICAL_TOPIC_RETRY_HINTS):
        for facet in FINANCE_RETRY_FACETS:
            add_suggestion(f"{_rewrite_finance_retry_query(base_query, facet)}发生了哪些变化")

    return suggestions[:4]


def _build_no_result_guidance(query: str, doc_ids: list[str] | None) -> str:
    lines = ["## 检索结果", "", "本轮没有命中到可直接使用的内部知识片段。", "", "---"]
    if doc_ids:
        lines.append("先不要因为这一轮空结果就直接换到别的书层，更不要立刻跳到 `web_search`。")
        lines.append("如果这些 `doc_ids` 已经来自 `book_search` 里最匹配的书，先保持同一批相关 `doc_ids`，只改一个变量继续重试。")
    else:
        lines.append("先不要立刻跳到 `web_search`；优先回到 `book_search` 找到更匹配的书，再在那一层继续检索。")

    lines.append("优先重试顺序：")
    lines.append("1. 保留原时期/制度/人物锚点，只把 query 缩窄成一个更小的专题分面。")
    lines.append("2. 把时期词换成正文里更常见的同义叫法，例如 `清代末期` → `晚清` / `清末`。")
    lines.append("3. 像“某时期财政情况”这种宽问题，先拆成 `财政收入结构`、`财政支出结构`、`财政政策` 之类的小问题。")
    lines.append("4. 由于库里大多是长段正文，优先改写成带锚点的句子型专业 query，不要写成关键词堆砌。")

    suggestions = _build_retry_query_suggestions(query)
    if suggestions:
        lines.append("建议下一轮 query：")
        for suggestion in suggestions:
            lines.append(f"- `{suggestion}`")

    lines.append("只有在同一批最相关书里做过这些 grounded retries 仍然没有证据时，才考虑换书层；`web_search` 放在更后面。")
    return "\n".join(lines)


def _merge_scopes(*scope_groups: list[str] | None) -> list[str] | None:
    seen: set[str] = set()
    merged: list[str] = []
    for scope in SEARCH_SCOPE_ORDER:
        for group in scope_groups:
            if not group or scope not in group or scope in seen:
                continue
            seen.add(scope)
            merged.append(scope)
    return merged or None


def _infer_scopes_from_doc_ids(
    doc_ids: list[str] | None,
    *,
    thread_id: str | None,
    user_id: str | None,
) -> list[str] | None:
    if not doc_ids:
        return None

    candidate_map = {
        candidate.doc_id: candidate.scope
        for candidate in list_book_catalog(thread_id=thread_id, user_id=user_id)
        if candidate.scope in ALLOWED_SEARCH_SCOPES
    }
    inferred: list[str] = []
    for doc_id in doc_ids:
        scope = candidate_map.get(doc_id)
        if scope and scope not in inferred:
            inferred.append(scope)
    return inferred or None


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


def _candidate_layer_key(candidate: BookCatalogEntry) -> str:
    if candidate.scope == "user":
        return "user"
    if candidate.scope == "thread":
        return "thread"
    return _normalize_type(candidate.type)


def _candidate_layer_label(layer: str) -> str:
    labels = {
        "user": "用户书籍",
        "thread": "当前线程书籍",
        CORE_TYPE: "核心通用书",
        SPECIALIZED_TYPE: "专题支撑书",
        REFERENCE_TYPE: "补充材料 / 参考工具书",
        "unknown": "其他候选书",
    }
    return labels.get(layer, "其他候选书")


def _format_candidate_brief(candidate: BookCatalogEntry) -> str:
    parts = [candidate.title, f"doc_id={candidate.doc_id}"]
    if candidate.score is not None:
        parts.append(f"相关度={candidate.score:.2f}")
    return " | ".join(parts)


def _validate_single_layer_doc_ids(
    doc_ids: list[str] | None,
    *,
    thread_id: str | None,
    user_id: str | None,
) -> str | None:
    if not doc_ids or len(doc_ids) <= 1:
        return None

    candidate_map = {
        candidate.doc_id: _candidate_layer_key(candidate)
        for candidate in list_book_catalog(thread_id=thread_id, user_id=user_id)
    }
    matched_layers: dict[str, list[str]] = {}
    for doc_id in doc_ids:
        layer = candidate_map.get(doc_id)
        if not layer:
            continue
        matched_layers.setdefault(layer, []).append(doc_id)

    if len(matched_layers) <= 1:
        return None

    layer_parts = [
        f"{_candidate_layer_label(layer)}: {', '.join(ids)}"
        for layer, ids in matched_layers.items()
    ]
    return (
        "Error: 当前 `doc_ids` 混入了不同层级的书目，不能在同一轮 `knowledge_search` 里批量检索。\n"
        "请一次只传一个层级的 `doc_ids`，同层内可以多本一起检索；跨层时请分多轮执行。\n"
        f"检测到的层级: {' | '.join(layer_parts)}"
    )


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
        for candidate in items[:5]:
            lines.append(f"- {_format_candidate_brief(candidate)}")
        if len(items) > 5:
            lines.append(f"- 其余 {len(items) - 5} 本已省略")
        lines.append(f"doc_ids: {', '.join(candidate.doc_id for candidate in items)}")
        lines.append("")

    user_doc_ids = ", ".join(candidate.doc_id for candidate in grouped["user"])
    thread_doc_ids = ", ".join(candidate.doc_id for candidate in grouped["thread"])
    core_doc_ids = ", ".join(candidate.doc_id for candidate in grouped[CORE_TYPE])
    specialized_doc_ids = ", ".join(candidate.doc_id for candidate in grouped[SPECIALIZED_TYPE])
    reference_doc_ids = ", ".join(candidate.doc_id for candidate in grouped[REFERENCE_TYPE])

    lines.append("---")
    lines.append("检索规则:")
    lines.append("1. 一次只批量检索一个层级的书目；不要混传不同层级的 `doc_ids`。")
    lines.append("2. 同层内可多本一起传给 `knowledge_search`。")
    lines.append("3. 默认顺序：用户书籍 -> 当前线程书籍 -> 核心通用书 -> 专题支撑书 -> 补充材料。")
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
    5. `scopes` is a hard filter. If you already pass `doc_ids` from
       `book_search`, do not also force an incompatible scope. When in doubt,
       omit `scopes` and let the `doc_ids` control the search.
    6. Keep `query` close to the user's wording and key anchors. Preserve
       book names, people, periods, institutions, years, and policy terms.
       Prefer a sentence-like professional query over a keyword pile-up.
       Do not write a bag of terms like `清代末期财政情况 财政收支结构 财政政策 财政危机`.
       Do not turn the query into a long meta sentence like “I need to search
       for ...”, and do not over-shorten it into something vaguer than the
       user's actual question.

    This tool searches through curated internal documents and returns relevant
    knowledge snippets with source document references.

    Args:
        query: Search terms describing what evidence you need. Prefer
            sentence-like, source-anchored phrasing over keyword pile-ups or
            meta narration.
        doc_ids: Optional comma-separated candidate book IDs from `book_search`.
            Prefer this for narrowing to known relevant books.
        scopes: Optional comma-separated hard filters: `user`, `thread`, `global`.
            Only set this when you intentionally want to exclude other scopes.
    """
    try:
        from src.community.knowledge_base.retriever import get_retriever

        retriever = get_retriever()
        thread_id = runtime.context.get("thread_id")
        user_id = runtime.context.get("user_id")
        parsed_doc_ids = _parse_doc_ids(doc_ids)
        parsed_scopes = _parse_scopes(scopes)
        mixed_layer_error = _validate_single_layer_doc_ids(
            parsed_doc_ids,
            thread_id=thread_id,
            user_id=user_id,
        )
        if mixed_layer_error:
            return mixed_layer_error
        inferred_scopes = _infer_scopes_from_doc_ids(
            parsed_doc_ids,
            thread_id=thread_id,
            user_id=user_id,
        )
        effective_scopes = _merge_scopes(parsed_scopes, inferred_scopes)
        results = retriever.search(
            query,
            thread_id=thread_id,
            user_id=user_id,
            doc_ids=parsed_doc_ids,
            scopes=effective_scopes,
        )
    except Exception as e:
        return f"Error searching knowledge base: {e}"

    if not results:
        return _build_no_result_guidance(query, parsed_doc_ids)

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
    formatted_output += "如果你已经从 `book_search` 拿到了 `doc_ids`，优先继续围绕这些书换一个更贴近用户原问题的查询，不要随手改成更空泛的短词。\n"
    formatted_output += "本库大多是长段正文，优先使用带锚点的句子型专业 query，不要把多个专题词机械并列成关键词串。\n"
    formatted_output += "只有在你明确想排除某个范围时才传 `scopes`；`scopes` 是硬过滤，和 `doc_ids` 会取交集，传错会把本该能搜到的书直接滤掉。\n"
    formatted_output += "如果某条结果看起来像目录、标题、页眉页脚、边栏、图表标题或过短片段，把它当作导航线索，不要直接拿来支撑最终结论。\n"
    formatted_output += "遇到这类线索时，继续搜索对应的目录词、章节名、阶段名、制度名，再调用 `knowledge_locate` 展开附近正文。\n"
    formatted_output += "使用答案时，直接复制上面的 `citation:` 行，不要自己重写。\n"
    formatted_output += "如果需要更多上下文，调用 `knowledge_locate`；不要去读原始 PDF 或 `.structured.json`。\n"
    formatted_output += "只有在你已经尝试了合理的换 query / 换书层 / `knowledge_locate` 展开后仍然没有足够证据时，才使用 `【无法回答】` 开头拒答。"

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
