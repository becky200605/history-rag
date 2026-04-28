from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
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
    BOOK_LAYER_ORDER,
    REFERENCE_TYPE,
    SPECIALIZED_TYPE,
    BookCatalogEntry,
    UNFILED_FOLDER_NAME,
    filter_book_catalog_entries,
    list_book_catalog,
    render_book_catalog_directory_tree,
    search_book_catalog,
)
from src.community.knowledge_base.book_metadata import normalize_folder_path
from src.community.knowledge_base.citations import resolve_result_citation_context
from src.community.knowledge_base.locator import LocatedDocument, extract_document_context, locate_document
from src.community.knowledge_base.reading_state import (
    COVERED_DOC_IDS_KEY,
    READING_SET_DOC_IDS_KEY,
    READING_SET_HUMAN_INDEX_KEY,
    READING_SET_QUERY_KEY,
    READING_SET_TITLES_KEY,
    latest_human_index,
)

BOOK_SEARCH_TOP_K = 20
KNOWLEDGE_SEARCH_TOP_K = 6
KNOWLEDGE_RESULT_MAX_CHARS = 1400
KNOWLEDGE_RESULT_MAX_LINES = 36
BOOK_READING_SET_LIMIT = 6
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
logger = logging.getLogger(__name__)


def _tool_runtime_state(runtime: ToolRuntime[ContextT, ThreadState]) -> dict[str, Any] | None:
    state = getattr(runtime, "state", None)
    return state if isinstance(state, dict) else None


def _list_book_catalog_for_tools(
    *,
    thread_id: str | None,
    user_id: str | None,
    include_search_content: bool,
    caller: str,
) -> list[BookCatalogEntry]:
    try:
        return list_book_catalog(
            thread_id=thread_id,
            user_id=user_id,
            include_search_content=include_search_content,
            caller=caller,
        )
    except TypeError:
        return list_book_catalog(thread_id=thread_id, user_id=user_id)


def _select_reading_set_candidates(
    candidates: list[BookCatalogEntry],
    *,
    limit: int = BOOK_READING_SET_LIMIT,
) -> list[BookCatalogEntry]:
    if len(candidates) <= limit:
        return list(candidates)

    selected: list[BookCatalogEntry] = []
    selected_ids: set[str] = set()

    for candidate in candidates[:limit]:
        if candidate.doc_id in selected_ids:
            continue
        selected.append(candidate)
        selected_ids.add(candidate.doc_id)

    for layer in BOOK_LAYER_ORDER:
        layer_candidate = next(
            (candidate for candidate in candidates if _candidate_layer_key(candidate) == layer),
            None,
        )
        if layer_candidate is None or layer_candidate.doc_id in selected_ids:
            continue
        selected.append(layer_candidate)
        selected_ids.add(layer_candidate.doc_id)

    return selected[:limit]


def _update_runtime_reading_set(
    runtime: ToolRuntime[ContextT, ThreadState],
    *,
    query: str,
    candidates: list[BookCatalogEntry],
) -> None:
    state = _tool_runtime_state(runtime)
    if state is None:
        return

    selected = _select_reading_set_candidates(candidates)
    state[READING_SET_DOC_IDS_KEY] = [candidate.doc_id for candidate in selected]
    state[READING_SET_TITLES_KEY] = {
        candidate.doc_id: candidate.title for candidate in selected if candidate.doc_id and candidate.title
    }
    state[COVERED_DOC_IDS_KEY] = []
    state[READING_SET_QUERY_KEY] = query.strip()
    state[READING_SET_HUMAN_INDEX_KEY] = latest_human_index(state.get("messages"))


def _mark_runtime_covered_doc_ids(
    runtime: ToolRuntime[ContextT, ThreadState],
    doc_ids: list[str] | None,
) -> None:
    state = _tool_runtime_state(runtime)
    if state is None or not doc_ids:
        return

    reading_set = state.get(READING_SET_DOC_IDS_KEY)
    if not isinstance(reading_set, list) or not reading_set:
        return

    reading_set_ids = {str(item).strip() for item in reading_set if str(item).strip()}
    normalized_doc_ids = [doc_id.strip() for doc_id in doc_ids if doc_id and doc_id.strip() in reading_set_ids]
    if not normalized_doc_ids:
        return

    existing = state.get(COVERED_DOC_IDS_KEY)
    existing_ids = [str(item).strip() for item in existing] if isinstance(existing, list) else []
    seen = set(existing_ids)
    for doc_id in normalized_doc_ids:
        if doc_id in seen:
            continue
        existing_ids.append(doc_id)
        seen.add(doc_id)
    state[COVERED_DOC_IDS_KEY] = existing_ids


def _split_loose_delimited_values(
    value: str | list[str] | tuple[str, ...] | set[str] | None,
) -> list[str] | None:
    if value is None:
        return None

    raw_items = [value] if isinstance(value, str) else list(value)
    if isinstance(value, str):
        stripped_value = value.strip()
        if stripped_value.startswith("[") and stripped_value.endswith("]"):
            try:
                decoded = json.loads(stripped_value)
            except Exception:
                decoded = None
            if isinstance(decoded, list):
                raw_items = decoded

    parsed: list[str] = []
    seen: set[str] = set()

    for raw_item in raw_items:
        for candidate in re.split(r"[,，、;\n；]+", str(raw_item)):
            normalized = candidate.strip().strip("`\"'")
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            parsed.append(normalized)

    return parsed or None


def _parse_doc_ids(doc_ids: str | list[str] | tuple[str, ...] | set[str] | None) -> list[str] | None:
    if not doc_ids:
        return None
    if isinstance(doc_ids, str):
        stripped = doc_ids.strip()
        matches = re.findall(r"\[([^\[\]]+)\]", stripped)
        remainder = re.sub(r"\[[^\[\]]+\]", "", stripped).strip()
        if matches and not remainder:
            parsed = [item.strip() for item in matches if item.strip()]
            if not parsed:
                raise ValueError("Invalid `doc_ids` format: no non-empty doc_id found.")
            return parsed
        parsed = _split_loose_delimited_values(stripped)
        if parsed:
            return parsed
        raise ValueError(
            "Invalid `doc_ids` format. Pass either bracket blocks like "
            "`[doc_id_1][doc_id_2][doc_id_3]` or a delimited string such as "
            "`doc_id_1, doc_id_2`."
        )
    return _split_loose_delimited_values(doc_ids)


def _parse_folder_paths(folder_paths: str | list[str] | tuple[str, ...] | None) -> list[str] | None:
    if folder_paths is None:
        return None
    parsed: list[str] = []
    seen: set[str] = set()
    for candidate in _split_loose_delimited_values(folder_paths) or []:
        normalized = normalize_folder_path(candidate)
        if normalized == "未归档":
            normalized = UNFILED_FOLDER_NAME
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        parsed.append(normalized)
    return parsed or None


def _parse_knowledge_folders(
    knowledge_folders: str | list[str] | tuple[str, ...] | None,
) -> list[str] | None:
    return _parse_folder_paths(knowledge_folders)


def _normalize_knowledge_folder_candidate(value: str) -> str:
    normalized = normalize_folder_path(value)
    if normalized:
        return normalized
    return re.sub(r"\s+", " ", value.strip()).strip("/")


def _coerce_runtime_string_list(value: object) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        parsed = [item.strip() for item in value.split(",") if item.strip()]
        return parsed or None
    if isinstance(value, (list, tuple, set)):
        parsed = [str(item).strip() for item in value if str(item).strip()]
        return parsed or None
    return None


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


def _runtime_selected_doc_ids(runtime: ToolRuntime[ContextT, ThreadState]) -> list[str] | None:
    return _coerce_runtime_string_list(runtime.context.get("selected_doc_ids"))


def _runtime_selected_scopes(runtime: ToolRuntime[ContextT, ThreadState]) -> list[str] | None:
    selected_scopes = _coerce_runtime_string_list(runtime.context.get("selected_sources_scope"))
    return _parse_scopes(",".join(selected_scopes)) if selected_scopes else None


def _entry_folder_path(entry: BookCatalogEntry) -> str | None:
    normalized = normalize_folder_path(entry.folder_path)
    if normalized:
        return normalized
    relative_parent = normalize_folder_path(str(Path(entry.filename).parent))
    if relative_parent:
        return relative_parent
    return UNFILED_FOLDER_NAME


def _entry_matches_any_knowledge_folder(entry: BookCatalogEntry, knowledge_folders: list[str]) -> bool:
    entry_folder = _entry_folder_path(entry)
    if not entry_folder:
        return False
    return any(
        entry_folder == folder or entry_folder.startswith(f"{folder}/")
        for folder in knowledge_folders
    )


def _visible_catalog_entries(
    *,
    thread_id: str | None,
    user_id: str | None,
    selected_doc_ids: list[str] | None,
    selected_scopes: list[str] | None,
) -> list[BookCatalogEntry]:
    return filter_book_catalog_entries(
        _list_book_catalog_for_tools(
            thread_id=thread_id,
            user_id=user_id,
            include_search_content=False,
            caller="tools._visible_catalog_entries",
        ),
        doc_ids=selected_doc_ids,
        scopes=selected_scopes,
    )


def _build_knowledge_folder_guidance(
    *,
    visible_entries: list[BookCatalogEntry],
    reason: str,
) -> str:
    directory_tree = render_book_catalog_directory_tree(visible_entries) or "（当前范围没有可见知识库目录）"
    return (
        f"{reason}\n"
        "`knowledge_folders` 指的是知识库目录树中的逻辑目录，不是 sandbox / 容器 / 本地文件系统路径。\n"
        "也不要填写 `用户书籍`、`当前线程书籍`、`核心通用书`、`专题支撑书`、`补充材料`、`参考工具书` 这类层级标签；它们只是系统内部的分层概念，不是可检索目录。\n"
        "也不要填写 `user`、`thread`、`global` 这类 scope 标签；它们是资料范围过滤标签，不是知识库目录。\n"
        "不要把它理解成 `/mnt/...`、`./...`、`knowledge/docs/...` 这类本地目录，也不要试图通过 `ls`、`read_file`、`bash` 等其他方式自己推断它。\n"
        "请直接从下面的知识库目录树中复制目录名来填写 `knowledge_folders`。\n\n"
        "## 可见知识库目录树\n\n"
        f"{directory_tree}\n\n"
        "示例: `knowledge_folders=[\"人物传记/晚清\", \"档案资料/盛宣怀\"]`"
    )


def _looks_like_local_filesystem_path(value: str) -> bool:
    normalized = value.strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    return (
        normalized.startswith(("/", "./", "../", "~"))
        or lowered.startswith(("mnt/", "knowledge/", "backend/", "frontend/"))
        or "\\" in normalized
        or lowered.endswith((".pdf", ".md", ".txt", ".json", ".jsonl"))
    )


_VIRTUAL_KNOWLEDGE_FOLDER_LABELS = {
    "用户书籍",
    "当前线程书籍",
    "系统知识库",
    "核心通用书",
    "专题支撑书",
    "补充材料",
    "参考工具书",
    "补充材料 / 参考工具书",
    "其他资料",
    "user",
    "thread",
    "global",
}


def _looks_like_virtual_knowledge_folder_label(value: str) -> bool:
    normalized = _normalize_knowledge_folder_candidate(value)
    return normalized in _VIRTUAL_KNOWLEDGE_FOLDER_LABELS


def _intersect_doc_ids(
    requested_doc_ids: list[str] | None,
    selected_doc_ids: list[str] | None,
) -> list[str] | None:
    if not requested_doc_ids:
        return selected_doc_ids
    if not selected_doc_ids:
        return requested_doc_ids
    allowed = set(selected_doc_ids)
    intersection = [doc_id for doc_id in requested_doc_ids if doc_id in allowed]
    return intersection or []


def _format_doc_id_blocks(doc_ids: list[str]) -> str:
    return "".join(f"[{doc_id}]" for doc_id in doc_ids)


def _normalize_doc_id_match_key(value: str) -> str:
    return re.sub(r"\s+", "", value).strip()


def _resolve_requested_doc_ids(
    requested_doc_ids: list[str] | None,
    *,
    visible_entries: list[BookCatalogEntry],
) -> tuple[list[str] | None, list[str], list[str]]:
    if not requested_doc_ids:
        return None, [], []

    exact_doc_ids = {entry.doc_id: entry.doc_id for entry in visible_entries}
    normalized_doc_ids: dict[str, list[str]] = {}
    for entry in visible_entries:
        normalized_key = _normalize_doc_id_match_key(entry.doc_id)
        normalized_doc_ids.setdefault(normalized_key, []).append(entry.doc_id)

    resolved: list[str] = []
    missing: list[str] = []
    ambiguous: list[str] = []

    for requested_doc_id in requested_doc_ids:
        if requested_doc_id in exact_doc_ids:
            resolved.append(exact_doc_ids[requested_doc_id])
            continue

        normalized_key = _normalize_doc_id_match_key(requested_doc_id)
        matches = normalized_doc_ids.get(normalized_key, [])
        if len(matches) == 1:
            resolved.append(matches[0])
            continue
        if len(matches) > 1:
            ambiguous.append(requested_doc_id)
            continue
        missing.append(requested_doc_id)

    return resolved, missing, ambiguous


def _resolve_requested_filename(
    requested_filename: str | None,
    *,
    visible_entries: list[BookCatalogEntry],
) -> tuple[str | None, bool]:
    if not requested_filename:
        return None, False

    exact_filenames = {entry.filename: entry.filename for entry in visible_entries}
    if requested_filename in exact_filenames:
        return exact_filenames[requested_filename], False

    normalized_requested = _normalize_doc_id_match_key(requested_filename)
    normalized_matches = [
        entry.filename
        for entry in visible_entries
        if _normalize_doc_id_match_key(entry.filename) == normalized_requested
    ]
    if len(normalized_matches) == 1:
        return normalized_matches[0], False
    if len(normalized_matches) > 1:
        return None, True
    return None, False


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
        lines.append("先在同一批 `doc_ids` 里最多 grounded 重试 2 次。")
        lines.append("如果 2 次后仍然没有结果，直接调用 `knowledge_locate(doc_id=...)` 做原文定位；优先看目录、序言、章节开头，再顺着相关板块继续找正文。")
    else:
        lines.append("先回到 `book_search` 找更匹配的书，再继续检索。")

    suggestions = _build_retry_query_suggestions(query)
    if suggestions:
        lines.append("建议下一轮 query：")
        for suggestion in suggestions[:2]:
            lines.append(f"- `{suggestion}`")
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
        for candidate in _list_book_catalog_for_tools(
            thread_id=thread_id,
            user_id=user_id,
            include_search_content=False,
            caller="tools._infer_scopes_from_doc_ids",
        )
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
    return f"[citation:{citation_label}](<{citation_link}>)"


def _build_locate_excerpt_citation(
    *,
    document: LocatedDocument,
    excerpt: dict[str, Any],
    thread_id: str | None,
    user_id: str | None,
) -> str | None:
    citation_context = resolve_result_citation_context(
        {
            "filename": document.filename,
            "metadata": {
                "title": document.title,
                "filename": document.filename,
                "scope": document.scope,
                "page_no": excerpt.get("page_no"),
                "pdf_page_no": excerpt.get("pdf_page_no"),
                "paragraph_no": excerpt.get("paragraph_no"),
            },
        },
        thread_id=thread_id,
        user_id=user_id,
    )
    citation_label = _build_citation_label(
        str(citation_context["citation_title"] or document.title),
        citation_context["citation_page_no"],
        citation_context["citation_pdf_page_no"],
        citation_context["citation_paragraph_no"],
        page=citation_context["citation_page"],
    )
    return _build_citation(
        citation_label,
        citation_context.get("citation_url") or citation_context.get("source_url"),
    )


def _looks_like_navigation_page(page_text: str) -> bool:
    normalized = " ".join(page_text.split()).lower()
    if not normalized:
        return False
    if any(keyword in normalized for keyword in ("目录", "contents", "table of contents", "绪论", "引言", "序言", "凡例")):
        return True

    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    if len(lines) < 3:
        return False

    dotted_lines = sum(1 for line in lines if "....." in line or "……" in line)
    numbered_lines = sum(1 for line in lines if line and line[-1].isdigit())
    chapter_lines = sum(1 for line in lines if re.search(r"第[一二三四五六七八九十百〇0-9]+[章节编卷部]", line))
    return dotted_lines >= 2 or numbered_lines >= 3 or chapter_lines >= 2


def _build_navigation_locate_preview(
    *,
    payload: dict[str, Any],
    max_pages: int = 3,
) -> list[dict[str, Any]]:
    pages = payload.get("pages") or []
    if not pages:
        return []

    selected_pages: list[dict[str, Any]] = []
    seen_pdf_pages: set[int] = set()

    def add_page(page: dict[str, Any]) -> None:
        pdf_page_no = int(page.get("pdf_page_no") or page.get("page_no") or 0)
        if pdf_page_no in seen_pdf_pages:
            return
        seen_pdf_pages.add(pdf_page_no)
        selected_pages.append(page)

    for page in pages[: min(len(pages), 20)]:
        page_text = str(page.get("text") or "")
        if _looks_like_navigation_page(page_text):
            add_page(page)
        if len(selected_pages) >= max_pages:
            break

    if len(selected_pages) < max_pages:
        for page in pages[: min(len(pages), 6)]:
            add_page(page)
            if len(selected_pages) >= max_pages:
                break

    previews: list[dict[str, Any]] = []
    for page in selected_pages[:max_pages]:
        page_text = str(page.get("text") or "").strip()
        if not page_text:
            paragraphs = page.get("paragraphs") or []
            page_text = "\n\n".join(
                str(paragraph.get("text") or "").strip()
                for paragraph in paragraphs
                if str(paragraph.get("text") or "").strip()
            ).strip()
        if not page_text:
            continue
        previews.append(
            {
                "page_no": page.get("page_no"),
                "pdf_page_no": page.get("pdf_page_no"),
                "book_page_no": page.get("book_page_no"),
                "text": page_text,
                "is_navigation_page": _looks_like_navigation_page(page_text),
            }
        )
    return previews


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
    if candidate.folder_path:
        parts.append(f"目录={candidate.folder_path}")
    return " | ".join(parts)


@tool("book_search", parse_docstring=True)
def book_search_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    query: str,
    knowledge_folders: list[str],
) -> str:
    """Search candidate books before full-text retrieval.

    Use this tool first for historical/domain questions. It finds likely user
    books and system books before full-text retrieval so the agent can search
    in a layered order instead of jumping directly into the whole corpus.

    Args:
        query: The user's research question or topic description.
        knowledge_folders: Required knowledge-base folder array. These are
            logical folders from the injected knowledge directory tree, not
            sandbox/local filesystem paths. `book_search` is not allowed to run
            as a whole-corpus catalog search; it must stay inside the chosen
            knowledge folders.
    """
    started_at = time.perf_counter()
    thread_id = runtime.context.get("thread_id")
    user_id = runtime.context.get("user_id")
    selected_doc_ids = _runtime_selected_doc_ids(runtime)
    selected_scopes = _runtime_selected_scopes(runtime)
    logger.info(
        "Book search start: query=%r thread_id=%s has_user=%s selected_doc_ids=%s selected_scopes=%s raw_knowledge_folders=%s",
        query,
        thread_id,
        bool(user_id),
        len(selected_doc_ids or []),
        ",".join(selected_scopes or []),
        _split_loose_delimited_values(knowledge_folders) or [],
    )
    visible_entries = _visible_catalog_entries(
        thread_id=thread_id,
        user_id=user_id,
        selected_doc_ids=selected_doc_ids,
        selected_scopes=selected_scopes,
    )
    raw_knowledge_folders = _split_loose_delimited_values(knowledge_folders) or []
    parsed_knowledge_folders = _parse_knowledge_folders(knowledge_folders)
    if not parsed_knowledge_folders:
        logger.info(
            "Book search rejected: query=%r reason=missing_knowledge_folders elapsed_ms=%.1f",
            query,
            (time.perf_counter() - started_at) * 1000,
        )
        return _build_knowledge_folder_guidance(
            visible_entries=visible_entries,
            reason="Error: `book_search` 禁止整库全量搜索，必须传入 `knowledge_folders`。",
        )
    if any(_looks_like_virtual_knowledge_folder_label(folder) for folder in raw_knowledge_folders):
        logger.info(
            "Book search rejected: query=%r reason=virtual_folder_labels elapsed_ms=%.1f",
            query,
            (time.perf_counter() - started_at) * 1000,
        )
        return _build_knowledge_folder_guidance(
            visible_entries=visible_entries,
            reason="Error: 你传入的 `knowledge_folders` 是层级标签（如 `用户书籍`、`核心通用书`），不是知识库逻辑目录。",
        )
    if any(_looks_like_local_filesystem_path(folder) for folder in raw_knowledge_folders):
        logger.info(
            "Book search rejected: query=%r reason=local_filesystem_path elapsed_ms=%.1f",
            query,
            (time.perf_counter() - started_at) * 1000,
        )
        return _build_knowledge_folder_guidance(
            visible_entries=visible_entries,
            reason="Error: 你传入的 `knowledge_folders` 看起来像本地 sandbox 路径或文件名，不是知识库逻辑目录。",
        )
    if not any(
        _entry_matches_any_knowledge_folder(entry, parsed_knowledge_folders)
        for entry in visible_entries
    ):
        logger.info(
            "Book search rejected: query=%r reason=folder_not_visible visible_entries=%s parsed_knowledge_folders=%s elapsed_ms=%.1f",
            query,
            len(visible_entries),
            ",".join(parsed_knowledge_folders),
            (time.perf_counter() - started_at) * 1000,
        )
        return _build_knowledge_folder_guidance(
            visible_entries=visible_entries,
            reason="Error: 当前 `knowledge_folders` 在知识库目录树中没有匹配到任何可见目录。",
        )
    search_started_at = time.perf_counter()
    candidates = search_book_catalog(
        query,
        thread_id=thread_id,
        user_id=user_id,
        top_k=BOOK_SEARCH_TOP_K,
        doc_ids=selected_doc_ids,
        scopes=selected_scopes,
        folder_paths=parsed_knowledge_folders,
        entries=visible_entries,
    )
    logger.info(
        "Book search catalog phase complete: query=%r candidates=%s visible_entries=%s parsed_knowledge_folders=%s elapsed_ms=%.1f",
        query,
        len(candidates),
        len(visible_entries),
        ",".join(parsed_knowledge_folders),
        (time.perf_counter() - search_started_at) * 1000,
    )
    if not candidates:
        _update_runtime_reading_set(runtime, query=query, candidates=[])
        if selected_doc_ids:
            logger.info(
                "Book search no candidates: query=%r selected_doc_ids=%s elapsed_ms=%.1f",
                query,
                len(selected_doc_ids or []),
                (time.perf_counter() - started_at) * 1000,
            )
            return "当前对话已限定在所选资料范围内，但这些资料里没有找到匹配的候选书目。"
        logger.info(
            "Book search no candidates: query=%r elapsed_ms=%.1f",
            query,
            (time.perf_counter() - started_at) * 1000,
        )
        return "No likely books found for this query."

    _update_runtime_reading_set(runtime, query=query, candidates=candidates)

    grouped = _group_book_candidates(candidates)
    lines = []
    lines.extend(["## 候选书目", ""])
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
        lines.append(f"doc_ids: {_format_doc_id_blocks([candidate.doc_id for candidate in items])}")
        lines.append("")

    user_doc_ids = _format_doc_id_blocks([candidate.doc_id for candidate in grouped["user"]]) if grouped["user"] else ""
    thread_doc_ids = _format_doc_id_blocks([candidate.doc_id for candidate in grouped["thread"]]) if grouped["thread"] else ""
    core_doc_ids = _format_doc_id_blocks([candidate.doc_id for candidate in grouped[CORE_TYPE]]) if grouped[CORE_TYPE] else ""
    specialized_doc_ids = _format_doc_id_blocks([candidate.doc_id for candidate in grouped[SPECIALIZED_TYPE]]) if grouped[SPECIALIZED_TYPE] else ""
    reference_doc_ids = _format_doc_id_blocks([candidate.doc_id for candidate in grouped[REFERENCE_TYPE]]) if grouped[REFERENCE_TYPE] else ""

    lines.append("---")
    lines.append("检索规则:")
    lines.append("1. 可将多本相关书一起传给 `knowledge_search`，允许混传不同层级的 `doc_ids`。")
    lines.append("2. 如果你已经确定一批书需要对读，优先直接用这批 `doc_ids` 联合检索。")
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
    if parsed_knowledge_folders:
        lines.append(f"knowledge_folders: {', '.join(parsed_knowledge_folders)}")
    logger.info(
        "Book search complete: query=%r grouped_user=%s grouped_thread=%s grouped_core=%s grouped_specialized=%s grouped_reference=%s elapsed_ms=%.1f",
        query,
        len(grouped["user"]),
        len(grouped["thread"]),
        len(grouped[CORE_TYPE]),
        len(grouped[SPECIALIZED_TYPE]),
        len(grouped[REFERENCE_TYPE]),
        (time.perf_counter() - started_at) * 1000,
    )
    return "\n".join(lines)


@tool("knowledge_search", parse_docstring=True)
def knowledge_search_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    query: str,
    doc_ids: str | list[str] | tuple[str, ...] | set[str] | None = None,
    scopes: str | None = None,
    knowledge_folders: list[str] | None = None,
) -> str:
    """Search the internal knowledge base for domain-specific information.

    This tool should usually be used after `book_search`, so retrieval can
    focus on the right books in a layered order instead of jumping into the
    whole corpus. It currently runs in lexical/BM25 mode: prioritize entity
    names, institutions, years, places, and policy terms, and keep the query
    in the same script/style as the target book whenever possible.

    Recommended use:
    1. First call `book_search(query=...)` to identify likely user/system books.
    2. Then call `knowledge_search` against the selected layer of books.
       Inside one layer, prefer passing multiple relevant `doc_ids` together for
       a first-pass batch search, instead of reading only one book first.
    3. Before calling, rewrite the user's need into 2-6 strong lexical anchors:
       people, institutions, place names, years, treaty/contract names, book
       terminology, and other source-facing keywords. Preserve traditional vs.
       simplified Chinese when the book clearly uses one form.
    4. After the batch pass, continue with narrower per-book queries and
       `knowledge_locate` on the books/locations that look promising.
    5. For exact quotation / page / paragraph lookups, you may use narrower
       scopes or doc filters and then call `knowledge_locate` for nearby context.
    6. `scopes` is a hard filter. If you already pass `doc_ids` from
       `book_search`, do not also force an incompatible scope. When in doubt,
       omit `scopes` and let the `doc_ids` control the search.
    7. If you already have `doc_ids` from `book_search`, let those book IDs
       drive retrieval directly; do not add an unnecessary folder constraint.
    8. You may pass `knowledge_folders` only when you intentionally want to
       constrain a search that is not already narrowed by `doc_ids`.
    9. Keep `query` close to the user's wording and key anchors. Preserve
       book names, people, periods, institutions, years, and policy terms.
       Prefer a sentence-like professional query over a keyword pile-up.
       Do not write a bag of terms like `清代末期财政情况 财政收支结构 财政政策 财政危机`.
       Do not turn the query into a long meta sentence like “I need to search
       for ...”, and do not over-shorten it into something vaguer than the
       user's actual question.

    This tool searches through curated internal documents and returns relevant
    paragraph-level snippets with page anchors and source references. Very
    short paragraphs are filtered out so the returned hits are more reusable.

    Args:
        query: Search terms describing what evidence you need. Prefer
            sentence-like, source-anchored phrasing over keyword pile-ups or
            meta narration.
        doc_ids: Optional candidate book IDs from `book_search`. Supports a
            string or array input. When passing a string, use strict bracket
            blocks like `[doc_id_1][doc_id_2][doc_id_3]`.
            Prefer this for narrowing to known relevant books. If present,
            `knowledge_search` should search these books directly.
        scopes: Optional comma-separated hard filters: `user`, `thread`, `global`.
            Only set this when you intentionally want to exclude other scopes.
        knowledge_folders: Optional knowledge-base folder array. These are
            logical folders from the injected knowledge directory tree, not
            sandbox/local filesystem paths. Use this only when you want folder
            scoping without explicit `doc_ids`.
    """
    started_at = time.perf_counter()
    try:
        thread_id = runtime.context.get("thread_id")
        user_id = runtime.context.get("user_id")
        try:
            parsed_doc_ids = _parse_doc_ids(doc_ids)
        except ValueError as exc:
            logger.info(
                "Knowledge search rejected: query=%r reason=invalid_doc_ids_format elapsed_ms=%.1f",
                query,
                (time.perf_counter() - started_at) * 1000,
            )
            return f"Error: {exc}"
        selected_doc_ids = _runtime_selected_doc_ids(runtime)
        logger.info(
            "Knowledge search start: query=%r thread_id=%s has_user=%s requested_doc_ids=%s selected_doc_ids=%s effective_doc_ids=%s scopes_arg=%r knowledge_folders=%s",
            query,
            thread_id,
            bool(user_id),
            len(parsed_doc_ids or []),
            len(selected_doc_ids or []),
            len(_intersect_doc_ids(parsed_doc_ids, selected_doc_ids) or []),
            scopes,
            _split_loose_delimited_values(knowledge_folders) or [],
        )
        parsed_scopes = _parse_scopes(scopes)
        selected_scopes = _runtime_selected_scopes(runtime)
        visible_entries = _visible_catalog_entries(
            thread_id=thread_id,
            user_id=user_id,
            selected_doc_ids=selected_doc_ids,
            selected_scopes=selected_scopes,
        )
        resolved_doc_ids, missing_doc_ids, ambiguous_doc_ids = _resolve_requested_doc_ids(
            parsed_doc_ids,
            visible_entries=visible_entries,
        )
        if ambiguous_doc_ids:
            logger.info(
                "Knowledge search rejected: query=%r reason=ambiguous_doc_ids ambiguous_doc_ids=%s elapsed_ms=%.1f",
                query,
                len(ambiguous_doc_ids),
                (time.perf_counter() - started_at) * 1000,
            )
            return (
                "Error: 以下 `doc_ids` 去除空格后匹配到多个候选，当前无法唯一确定："
                f"{_format_doc_id_blocks(ambiguous_doc_ids)}。"
                "请改用 `book_search` 返回的原样 `doc_ids`。"
            )
        if missing_doc_ids:
            logger.info(
                "Knowledge search rejected: query=%r reason=unknown_doc_ids missing_doc_ids=%s elapsed_ms=%.1f",
                query,
                len(missing_doc_ids),
                (time.perf_counter() - started_at) * 1000,
            )
            return (
                "Error: 以下 `doc_ids` 在当前可见资料范围内不存在："
                f"{_format_doc_id_blocks(missing_doc_ids)}。"
                "请使用 `book_search` 返回的原样 `doc_ids`，并保持 `[doc_id_1][doc_id_2]` 这种格式。"
            )
        effective_doc_ids = _intersect_doc_ids(resolved_doc_ids, selected_doc_ids)
        raw_knowledge_folders = _split_loose_delimited_values(knowledge_folders) or []
        parsed_knowledge_folders = _parse_knowledge_folders(knowledge_folders)
        if not effective_doc_ids and not parsed_knowledge_folders:
            logger.info(
                "Knowledge search rejected: query=%r reason=missing_doc_ids_and_knowledge_folders elapsed_ms=%.1f",
                query,
                (time.perf_counter() - started_at) * 1000,
            )
            return (
                "Error: `knowledge_search` 需要至少提供一种约束：`doc_ids` 或 `knowledge_folders`。"
                "如果你已经有 `book_search` 返回的 `doc_ids`，直接传 `doc_ids` 即可。"
            )
        if not effective_doc_ids and any(_looks_like_virtual_knowledge_folder_label(folder) for folder in raw_knowledge_folders):
            logger.info(
                "Knowledge search rejected: query=%r reason=virtual_folder_labels elapsed_ms=%.1f",
                query,
                (time.perf_counter() - started_at) * 1000,
            )
            return _build_knowledge_folder_guidance(
                visible_entries=visible_entries,
                reason="Error: 你传入的 `knowledge_folders` 是层级标签（如 `用户书籍`、`核心通用书`），不是知识库逻辑目录。",
            )
        if not effective_doc_ids and any(_looks_like_local_filesystem_path(folder) for folder in raw_knowledge_folders):
            logger.info(
                "Knowledge search rejected: query=%r reason=local_filesystem_path elapsed_ms=%.1f",
                query,
                (time.perf_counter() - started_at) * 1000,
            )
            return _build_knowledge_folder_guidance(
                visible_entries=visible_entries,
                reason="Error: 你传入的 `knowledge_folders` 看起来像本地 sandbox 路径或文件名，不是知识库逻辑目录。",
            )
        if not effective_doc_ids and not any(
            _entry_matches_any_knowledge_folder(entry, parsed_knowledge_folders)
            for entry in visible_entries
        ):
            logger.info(
                "Knowledge search rejected: query=%r reason=folder_not_visible visible_entries=%s parsed_knowledge_folders=%s elapsed_ms=%.1f",
                query,
                len(visible_entries),
                ",".join(parsed_knowledge_folders),
                (time.perf_counter() - started_at) * 1000,
            )
            return _build_knowledge_folder_guidance(
                visible_entries=visible_entries,
                reason="Error: 当前 `knowledge_folders` 在知识库目录树中没有匹配到任何可见目录。",
            )
        from src.community.knowledge_base.retriever import get_retriever

        retriever = get_retriever()
        inferred_scopes = _infer_scopes_from_doc_ids(
            effective_doc_ids,
            thread_id=thread_id,
            user_id=user_id,
        )
        effective_scopes = _merge_scopes(selected_scopes, parsed_scopes, inferred_scopes)
        applied_folder_paths = None if effective_doc_ids else parsed_knowledge_folders
        if effective_doc_ids and parsed_knowledge_folders:
            logger.info(
                "Knowledge search ignoring knowledge_folders because doc_ids are present: query=%r effective_doc_ids=%s raw_knowledge_folders=%s",
                query,
                len(effective_doc_ids or []),
                raw_knowledge_folders,
            )
        retrieval_started_at = time.perf_counter()
        results = retriever.search(
            query,
            thread_id=thread_id,
            user_id=user_id,
            doc_ids=effective_doc_ids,
            scopes=effective_scopes,
            folder_paths=applied_folder_paths,
        )
        logger.info(
            "Knowledge search retrieval phase complete: query=%r results=%s effective_doc_ids=%s effective_scopes=%s applied_folder_paths=%s elapsed_ms=%.1f",
            query,
            len(results),
            len(effective_doc_ids or []),
            ",".join(effective_scopes or []),
            ",".join(applied_folder_paths or []),
            (time.perf_counter() - retrieval_started_at) * 1000,
        )
    except Exception as e:
        logger.exception(
            "Knowledge search exception: query=%r elapsed_ms=%.1f",
            query,
            (time.perf_counter() - started_at) * 1000,
        )
        return f"Error searching knowledge base: {e}"

    if not results:
        logger.info(
            "Knowledge search no results: query=%r effective_doc_ids=%s elapsed_ms=%.1f",
            query,
            len(effective_doc_ids or []),
            (time.perf_counter() - started_at) * 1000,
        )
        return _build_no_result_guidance(query, effective_doc_ids)

    covered_doc_ids = []
    seen_covered_doc_ids: set[str] = set()
    for result in results:
        metadata = result.get("metadata", {})
        doc_id = str(metadata.get("origin_doc_id") or metadata.get("doc_id") or "").strip()
        if not doc_id or doc_id in seen_covered_doc_ids:
            continue
        seen_covered_doc_ids.add(doc_id)
        covered_doc_ids.append(doc_id)
    _mark_runtime_covered_doc_ids(runtime, covered_doc_ids)

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
        matched_keywords = [str(item) for item in result.get("matched_keywords") or [] if str(item).strip()]
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
        if matched_keywords:
            formatted_output += f"精确关键词命中: {'、'.join(matched_keywords)}\n"
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
    formatted_output += "这些结果已经做过词法/BM25 联合排序；回答前先归并不同来源里的分散证据，不要只摘取单个综述段落。\n"
    formatted_output += "如果你已经从 `book_search` 拿到了 `doc_ids`，优先继续围绕这些书换一个更贴近用户原问题的查询，不要随手改成更空泛的短词。\n"
    formatted_output += "优先把 query 写成带锚点的实体/机构/年份/地名/制度名检索式；必要时保留书里原有的繁体或异体写法。\n"
    formatted_output += "只有在你明确想排除某个范围时才传 `scopes`；`scopes` 是硬过滤，和 `doc_ids` 会取交集，传错会把本该能搜到的书直接滤掉。\n"
    formatted_output += "如果某条结果看起来像目录、标题、页眉页脚、边栏、图表标题或过短片段，把它当作导航线索，不要直接拿来支撑最终结论。\n"
    formatted_output += "遇到这类线索时，继续搜索对应的目录词、章节名、阶段名、制度名，再调用 `knowledge_locate` 展开附近正文。\n"
    formatted_output += "使用答案时，直接复制上面的 `citation:` 行，不要自己重写。\n"
    formatted_output += "如果需要更多上下文，调用 `knowledge_locate`；不要去读原始 PDF 或 `.structured.json`。\n"
    formatted_output += "只有在你已经尝试了合理的换 query / 换书层 / `knowledge_locate` 展开后仍然没有足够证据时，才使用 `【无法回答】` 开头拒答。"

    logger.info(
        "Knowledge search complete: query=%r returned_results=%s elapsed_ms=%.1f",
        query,
        min(len(results), KNOWLEDGE_SEARCH_TOP_K),
        (time.perf_counter() - started_at) * 1000,
    )
    return formatted_output


@tool("knowledge_locate", parse_docstring=True)
def knowledge_locate_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    doc_id: str | None = None,
    filename: str | None = None,
    page_no: int | None = None,
    page_no_end: int | None = None,
    pdf_page_no: int | None = None,
    pdf_page_no_end: int | None = None,
) -> str:
    """Locate full-page source context from a known document and page range.

    Use this after `knowledge_search` when you already know the relevant `doc_id`
    and need the full text of one page or a contiguous page range.
    If you only know the relevant book but not the exact location yet, you may
    call `knowledge_locate` with only `doc_id` (or `filename`) to get a
    navigation preview of likely目录/序言/开篇页，再据此继续按页定位正文。

    Args:
        doc_id: Optional document ID returned by `book_search` or `knowledge_search`.
        filename: Optional source filename if doc_id is unavailable.
        page_no: Optional original-book page number to inspect.
        page_no_end: Optional inclusive ending original-book page number for contiguous reading.
        pdf_page_no: Optional physical PDF page number to inspect.
        pdf_page_no_end: Optional inclusive ending PDF page number for contiguous reading.
    """
    if not doc_id and not filename:
        return "knowledge_locate requires either doc_id or filename."

    thread_id = runtime.context.get("thread_id")
    user_id = runtime.context.get("user_id")
    selected_doc_ids = _runtime_selected_doc_ids(runtime)
    selected_scopes = _runtime_selected_scopes(runtime)
    visible_entries = _visible_catalog_entries(
        thread_id=thread_id,
        user_id=user_id,
        selected_doc_ids=selected_doc_ids,
        selected_scopes=selected_scopes,
    )

    resolved_doc_id = doc_id
    if doc_id:
        resolved_doc_ids, missing_doc_ids, ambiguous_doc_ids = _resolve_requested_doc_ids(
            [doc_id],
            visible_entries=visible_entries,
        )
        if ambiguous_doc_ids:
            return (
                "Error: 当前 `knowledge_locate` 传入的 `doc_id` 去除空格后匹配到多个候选："
                f"{_format_doc_id_blocks(ambiguous_doc_ids)}。"
                "请改用 `book_search` / `knowledge_search` 返回的原样 `doc_id`。"
            )
        if missing_doc_ids:
            return (
                "Error: 当前 `knowledge_locate` 传入的 `doc_id` 在可见资料范围内不存在："
                f"{_format_doc_id_blocks(missing_doc_ids)}。"
                "请使用 `book_search` / `knowledge_search` 返回的原样 `doc_id`。"
            )
        resolved_doc_id = resolved_doc_ids[0] if resolved_doc_ids else doc_id

    resolved_filename = filename
    if filename:
        resolved_filename, filename_ambiguous = _resolve_requested_filename(
            filename,
            visible_entries=visible_entries,
        )
        if filename_ambiguous:
            return (
                "Error: 当前 `knowledge_locate` 传入的 `filename` 去除空格后匹配到多个候选。"
                "请改用更精确的原样文件名或直接传 `doc_id`。"
            )
        if resolved_filename is None:
            return (
                "Error: 当前 `knowledge_locate` 传入的 `filename` 在可见资料范围内不存在。"
                "请使用系统返回的原样 `filename` 或改传 `doc_id`。"
            )

    try:
        document = locate_document(
            thread_id,
            user_id=user_id,
            doc_id=resolved_doc_id,
            filename=resolved_filename,
        )
    except Exception as e:
        return f"Error locating document: {e}"
    if not document:
        return "No structured document found for the requested doc_id or filename."

    navigation_mode = (
        page_no is None
        and page_no_end is None
        and pdf_page_no is None
        and pdf_page_no_end is None
    )
    multi_page_mode = (
        (page_no is not None and page_no_end is not None and page_no_end != page_no)
        or (pdf_page_no is not None and pdf_page_no_end is not None and pdf_page_no_end != pdf_page_no)
    )

    if navigation_mode:
        previews = _build_navigation_locate_preview(payload=document.payload)
        if not previews:
            return "No navigation preview available for the requested document."

        _mark_runtime_covered_doc_ids(runtime, [str(document.doc_id)])

        lines = ["## 导航预览结果", ""]
        lines.append(f"标题: {document.title}")
        lines.append(f"doc_id: {document.doc_id}")
        lines.append(f"文件: {document.filename}")
        lines.append(f"范围: {document.scope}")
        lines.append(f"文档链接: {document.source_url}")
        if document.original_url and document.original_url != document.source_url:
            lines.append(f"原始文件: {document.original_url}")
        lines.append("")

        for index, preview in enumerate(previews, 1):
            location_text = _build_location_text(
                page_no=preview.get("page_no"),
                pdf_page_no=preview.get("pdf_page_no"),
                paragraph_no=None,
            ) or "未标注页码"
            kind = "目录/导航页" if preview.get("is_navigation_page") else "开篇预览页"
            lines.append(f"### 导航片段 {index}: {kind} - {location_text}")
            lines.append(str(preview.get("text") or "").strip())
            lines.append("")

        lines.append("---")
        lines.append(
            "下一步：从这些目录词、章节名、时期划分、专题板块里挑最相关的一项，"
            "再用对应页码继续调用 `knowledge_locate` 读取整页正文，或回到 `knowledge_search` 改成更贴近该板块的句子型 query。"
        )
        lines.append(
            "如果这是人物生平、经历、制度沿革这类零散问题，优先沿目录里的阶段/专题板块继续定位，不要只反复改关键词。"
        )
        lines.append(
            "为了减少反复调用，优先一次性读取更有代表性的连续页，不要机械地一页一页连续点开。"
        )
        return "\n".join(lines)

    try:
        excerpts = extract_document_context(
            payload=document.payload,
            page_no=page_no,
            page_no_end=page_no_end,
            pdf_page_no=pdf_page_no,
            pdf_page_no_end=pdf_page_no_end,
        )
    except Exception as e:
        return f"Error extracting source context: {e}"

    if not excerpts:
        return "No matching page context found in the structured document."

    _mark_runtime_covered_doc_ids(runtime, [str(document.doc_id)])

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
            paragraph_no=None,
        ) or "未标注页码"
        lines.append(f"### 整页 {index}: {location_text}")
        citation = _build_locate_excerpt_citation(
            document=document,
            excerpt=excerpt,
            thread_id=thread_id,
            user_id=user_id,
        )
        if citation:
            lines.append(f"citation: {citation}")
        lines.append(str(excerpt.get("text") or "").strip())
        lines.append("")

    lines.append("---")
    if multi_page_mode:
        lines.append(
            "这次 `knowledge_locate` 已按连续页范围展开，适合快速通读多页正文。"
        )
    else:
        lines.append("如果同一主题明显跨相邻多页，优先直接用 `page_no_end` / `pdf_page_no_end` 一次展开连续页。")
    lines.append("使用答案时，优先直接复制上面的 `citation:` 行，不要自己重写。")
    lines.append(
        "IMPORTANT: Use these excerpts as the follow-up source context. "
        "Do not inspect raw PDFs or `.structured.json` files directly."
    )
    return "\n".join(lines)
