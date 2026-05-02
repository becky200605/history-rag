from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from qdrant_client.models import Distance, VectorParams

from src.community.knowledge_base.retriever import get_embedding_model, get_qdrant_client
from src.config.knowledge_base_config import get_knowledge_base_config

TASK_MEMORY_COLLECTION_SUFFIX = "__task_memory"
TASK_MEMORY_TOP_K = 5
TASK_MEMORY_TITLE_MATCH_BOOST = 0.15
TASK_MEMORY_TITLE_PARTIAL_BOOST = 0.05


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def normalize_task_title(title: str | None) -> str:
    text = str(title or "").strip().lower()
    text = text.replace("：", ":")
    text = re.sub(r"\s+", " ", text)
    return text


def build_task_memory_id(title: str) -> str:
    normalized_title = normalize_task_title(title)
    return str(uuid5(NAMESPACE_URL, f"task-memory:{normalized_title}"))


def get_task_memory_collection_name(base_collection_name: str | None = None) -> str:
    config = get_knowledge_base_config()
    base_name = base_collection_name or config.qdrant.collection_name
    return f"{base_name}{TASK_MEMORY_COLLECTION_SUFFIX}"


def _normalize_string_list(value: list[str] | None) -> list[str]:
    return [str(item).strip() for item in value or [] if str(item).strip()]


def _build_task_memory_text(
    *,
    title: str,
    query: str,
    summary: str,
    findings: list[str],
    citations: list[str],
    open_questions: list[str],
) -> str:
    sections = [f"标题: {title.strip()}"]
    if query.strip():
        sections.append(f"查询: {query.strip()}")
    if summary.strip():
        sections.append(f"摘要:\n{summary.strip()}")
    if findings:
        sections.append("关键发现:\n" + "\n".join(f"- {item}" for item in findings))
    if citations:
        sections.append("关键引文:\n" + "\n".join(f"- {item}" for item in citations))
    if open_questions:
        sections.append("未解决缺口:\n" + "\n".join(f"- {item}" for item in open_questions))
    return "\n\n".join(section for section in sections if section.strip()).strip()


def _ensure_task_memory_collection() -> tuple[Any, Any, str]:
    config = get_knowledge_base_config()
    if not config.enabled or config.embedding is None:
        raise ValueError("Task memory requires the knowledge base and embedding model to be enabled")

    client = get_qdrant_client()
    embeddings = get_embedding_model()
    collection_name = get_task_memory_collection_name()

    try:
        client.get_collection(collection_name=collection_name)
    except Exception:
        sample_embedding = embeddings.embed_query("task-memory-collection-probe")
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=len(sample_embedding),
                distance=Distance.COSINE,
            ),
        )

    return client, embeddings, collection_name


def upsert_task_memory_record(
    *,
    title: str,
    query: str,
    summary: str,
    findings: list[str] | None = None,
    citations: list[str] | None = None,
    open_questions: list[str] | None = None,
    task_level: str,
    thread_id: str | None,
    user_id: str | None,
    task_id: str | None,
    status: str = "completed",
    raw_result: str | None = None,
) -> str | None:
    normalized_title = normalize_task_title(title)
    normalized_summary = str(summary or "").strip()
    if not normalized_title or not normalized_summary:
        return None

    normalized_findings = _normalize_string_list(findings)
    normalized_citations = _normalize_string_list(citations)
    normalized_open_questions = _normalize_string_list(open_questions)

    try:
        client, embeddings, collection_name = _ensure_task_memory_collection()
    except Exception:
        return None
    vector_store = QdrantVectorStore(
        client=client,
        collection_name=collection_name,
        embedding=embeddings,
    )

    content = _build_task_memory_text(
        title=title,
        query=query,
        summary=normalized_summary,
        findings=normalized_findings,
        citations=normalized_citations,
        open_questions=normalized_open_questions,
    )
    record_id = build_task_memory_id(title)
    document = Document(
        id=record_id,
        page_content=content,
        metadata={
            "record_id": record_id,
            "title": title.strip(),
            "normalized_title": normalized_title,
            "query": str(query or "").strip(),
            "summary": normalized_summary,
            "findings": normalized_findings,
            "citations": normalized_citations,
            "open_questions": normalized_open_questions,
            "task_level": task_level,
            "thread_id": thread_id,
            "user_id": user_id,
            "task_id": task_id,
            "status": status,
            "raw_result": str(raw_result or normalized_summary).strip(),
            "updated_at": _utc_now(),
        },
    )
    vector_store.add_documents([document], ids=[record_id])
    return record_id


def search_task_memory(
    query: str,
    *,
    title: str | None = None,
    top_k: int = TASK_MEMORY_TOP_K,
    task_level: str | None = None,
) -> list[dict[str, Any]]:
    normalized_query = str(query or "").strip()
    normalized_title = normalize_task_title(title)
    if not normalized_query and not normalized_title:
        return []

    try:
        client, embeddings, collection_name = _ensure_task_memory_collection()
    except Exception:
        return []
    vector_store = QdrantVectorStore(
        client=client,
        collection_name=collection_name,
        embedding=embeddings,
    )

    search_text = "\n".join(
        part
        for part in [
            f"标题: {title.strip()}" if title and title.strip() else "",
            f"查询: {normalized_query}" if normalized_query else "",
        ]
        if part
    )
    results = vector_store.similarity_search_with_score(
        search_text,
        k=max(top_k, 3),
        score_threshold=0.0,
    )

    min_score = float(get_knowledge_base_config().retrieval.score_threshold or 0.0)
    ranked: list[dict[str, Any]] = []
    seen_record_ids: set[str] = set()

    for doc, score in results:
        metadata = dict(doc.metadata or {})
        record_id = str(metadata.get("record_id") or doc.id or "").strip()
        if not record_id or record_id in seen_record_ids:
            continue
        if task_level and str(metadata.get("task_level") or "").strip() != task_level:
            continue

        candidate_title = str(metadata.get("title") or "").strip()
        candidate_normalized_title = normalize_task_title(candidate_title)
        weighted_score = float(score)
        if normalized_title and candidate_normalized_title == normalized_title:
            weighted_score += TASK_MEMORY_TITLE_MATCH_BOOST
        elif normalized_title and normalized_title in candidate_normalized_title:
            weighted_score += TASK_MEMORY_TITLE_PARTIAL_BOOST

        if weighted_score < min_score and candidate_normalized_title != normalized_title:
            continue

        seen_record_ids.add(record_id)
        ranked.append(
            {
                "content": doc.page_content,
                "metadata": metadata,
                "score": float(score),
                "weighted_score": weighted_score,
            }
        )

    ranked.sort(key=lambda item: item.get("weighted_score", item.get("score", 0.0)), reverse=True)
    return ranked[:top_k]


def render_task_memory_matches(
    results: list[dict[str, Any]],
    *,
    heading: str = "## 检索结果",
) -> str:
    if not results:
        return (
            f"{heading}\n\n"
            "本轮没有命中可直接复用的历史主任务/子任务结果。\n\n"
            "---\n"
            "把这次未命中视为当前主题没有可复用历史结果。不要继续改写 query 反复调用 `knowledge_search`；"
            "下一步直接从零走原始资料路线：主任务先用 `book_search` 选书并派发子任务；子任务再用 `knowledge_locate` 读目录、章节页、命中页或连续页正文。"
        )

    lines = [heading, ""]
    for index, item in enumerate(results, 1):
        metadata = item.get("metadata", {}) or {}
        title = str(metadata.get("title") or "未命名任务").strip()
        task_level = str(metadata.get("task_level") or "unknown").strip()
        query = str(metadata.get("query") or "").strip()
        summary = str(metadata.get("summary") or "").strip()
        findings = _normalize_string_list(metadata.get("findings"))
        citations = _normalize_string_list(metadata.get("citations"))
        open_questions = _normalize_string_list(metadata.get("open_questions"))
        thread_id = str(metadata.get("thread_id") or "").strip()
        task_id = str(metadata.get("task_id") or "").strip()

        lines.append(
            f"### 历史结果 {index}: {title} - 相关度: {float(item.get('weighted_score') or item.get('score') or 0.0):.2f}"
        )
        lines.append(f"任务层级: {task_level}")
        if query:
            lines.append(f"原始 query: {query}")
        if thread_id:
            lines.append(f"thread_id: {thread_id}")
        if task_id:
            lines.append(f"task_id: {task_id}")
        if summary:
            lines.append("任务结果:")
            lines.append(summary)
        if findings:
            lines.append("关键发现:")
            lines.extend(f"- {item}" for item in findings)
        if citations:
            lines.append("关键引文:")
            lines.extend(f"- {item}" for item in citations)
        if open_questions:
            lines.append("未解决缺口:")
            lines.extend(f"- {item}" for item in open_questions)
        lines.append("")

    lines.append("---")
    lines.append("这些历史主任务/子任务结果是当前任务的强制证据包，不等于当前问题已经自动完成，但也不能被忽略。")
    lines.append("后续行动必须先完成三类判断：`可直接复用`、`需要补充`、`应该纠正/弃用`。")
    lines.append("如果某条历史结果与当前问题高度重合，且已经包含可用结论和完整 citation，默认优先复用它；只把缺口部分交给新检索或子任务。")
    lines.append("如果复用历史结果中的事实、数字、分期、判断或缺口，最终回答必须把对应的完整 `[citation:...](...)` 链接一并带上。")
    lines.append("严禁把历史结果里的 citation 改写成空链接、裸 `[citation:...]`、普通书名或无 URL 的括号；无法确认完整链接时，把它列为证据缺口，不要当作有效引文。")
    return "\n".join(lines).strip()


def build_task_memory_injection_message(
    *,
    title: str,
    query: str,
    results: list[dict[str, Any]],
) -> str:
    rendered = render_task_memory_matches(results, heading="## 历史任务结果匹配")
    return (
        "<task_memory_matches>\n"
        "系统插入提示（不是用户的新问题）：以下是基于当前任务标题与 query 匹配到的历史主任务/子任务结果。\n"
        "这是当前任务的强制历史证据包。你必须先处理它，再决定是否需要新检索、下发子任务或直接综合回答。\n"
        f"当前任务标题：{title.strip() or '未命名任务'}\n"
        f"当前 query：{query.strip()}\n\n"
        f"{rendered}\n\n"
        "执行要求：\n"
        "1. 先逐条判断历史结果是 `可直接复用`、`需要补充`，还是 `应该纠正/弃用`；不要跳过这一步。\n"
        "2. 若历史结果已覆盖当前问题的大部分内容，不要重复派发同题子任务；只补查未解决缺口或疑似错误点。\n"
        "3. 综合回答时，必须显式吸收所有与当前问题高度相关的历史结论、关键发现、关键引文和未解决缺口。\n"
        "4. 复用历史结果时，只能复制完整 `[citation:标题](URL)` 链接；不完整、无 URL、空括号或格式损坏的 citation 不能输出为有效引文。\n"
        "5. 输出前自检：凡是引用历史结果中的事实、数字、页码、分期或因果判断，都必须在该句或该要点后带上对应完整 citation。\n"
        "</task_memory_matches>"
    )
