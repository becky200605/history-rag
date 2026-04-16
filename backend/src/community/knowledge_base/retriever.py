import logging
import re
import time

from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client import models

from src.community.knowledge_base.catalog import filter_book_catalog_entries, list_book_catalog
from src.community.knowledge_base.common import get_thread_collection_name
from src.community.knowledge_base.common import get_user_collection_name
from src.community.knowledge_base.lexical_search import lexical_search_documents
from src.config.knowledge_base_config import get_knowledge_base_config
from src.reflection import resolve_variable

"""
Module for retrieving documents from the knowledge base using Qdrant.
"""

logger = logging.getLogger(__name__)

_retriever_instance = None
DEFAULT_SEARCH_SCOPES = ("user", "thread", "global")
MIN_RESULT_LIMIT = 6
MIN_PER_QUERY_TOP_K = 4
MAX_QUERY_VARIANTS = 8
MAX_DOC_ID_QUERY_VARIANTS = 5
MIN_SUBSTANTIVE_WORD_UNITS = 50
EXACT_LOOKUP_HINTS = (
    "原文",
    "原句",
    "逐字",
    "页",
    "段",
    "行",
    "表",
    "图",
    "标题",
    "引文",
    "引用",
    "怎么写",
)
BROAD_EXPLORATION_HINTS = (
    "人物",
    "时期",
    "时代",
    "阶段",
    "历史",
    "沿革",
    "演变",
    "变迁",
    "经过",
    "原因",
    "影响",
    "生平",
    "经历",
    "活动",
    "思想",
    "政策",
    "制度",
)
PERIOD_QUERY_HINTS = (
    "时期",
    "时代",
    "阶段",
    "年间",
    "前期",
    "后期",
)
HISTORICAL_PERIOD_FACETS = {
    "民国": ["南京临时政府", "北洋政府", "南京国民政府", "抗日战争时期", "解放战争时期"],
    "民国时期": ["南京临时政府", "北洋政府", "南京国民政府", "抗日战争时期", "解放战争时期"],
    "晚清": ["同治时期", "光绪时期", "清末新政", "宣统时期", "预备立宪"],
    "清末": ["同治时期", "光绪时期", "清末新政", "宣统时期", "预备立宪"],
    "北洋时期": ["袁世凯时期", "皖系时期", "直系时期", "奉系时期"],
}
HISTORICAL_PERIOD_ALIASES = {
    "清代末期": ["晚清", "清末"],
    "晚清": ["清代末期", "清末"],
    "清末": ["晚清", "清代末期"],
    "民国时期": ["民国"],
    "民国": ["民国时期"],
}
HISTORICAL_TOPIC_RETRY_HINTS = (
    "情况",
    "概况",
    "变化",
    "变迁",
    "问题",
    "状况",
)
FINANCE_FACET_QUERIES = (
    "财政收入结构",
    "财政支出结构",
    "财政政策",
)
SCOPE_BOOSTS = {
    "user": 1.05,
    "thread": 1.0,
    "global": 0.95,
}


def _normalize_query_text(query: str) -> str:
    return re.sub(r"\s+", " ", query).strip()


def _count_word_units(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9]+", text))


def _is_substantive_result(result: dict, *, min_word_units: int = MIN_SUBSTANTIVE_WORD_UNITS) -> bool:
    content = str(result.get("content") or "").strip()
    if not content:
        return False
    return _count_word_units(content) >= min_word_units


def _looks_like_exact_lookup(query: str) -> bool:
    normalized = _normalize_query_text(query)
    if not normalized:
        return False
    if any(marker in normalized for marker in ("“", "”", "\"", "《", "》")):
        return True
    if re.search(r"第\s*\d+\s*[页段行章节卷]", normalized):
        return True
    return any(hint in normalized for hint in EXACT_LOOKUP_HINTS)


def _is_broad_exploration_query(query: str) -> bool:
    normalized = _normalize_query_text(query)
    if not normalized or _looks_like_exact_lookup(normalized):
        return False
    if len(normalized) <= 24:
        return True
    return any(hint in normalized for hint in BROAD_EXPLORATION_HINTS)


def _build_query_variants(query: str) -> list[dict[str, str | float]]:
    normalized = _normalize_query_text(query)
    if not normalized:
        return [{"query": query, "label": "原始问题", "weight": 1.0}]

    variants: list[dict[str, str | float]] = [
        {"query": normalized, "label": "原始问题", "weight": 1.0},
    ]
    seen = {normalized}

    def add_variant(text: str, label: str, weight: float) -> None:
        candidate = _normalize_query_text(text)
        if not candidate or candidate in seen or len(variants) >= MAX_QUERY_VARIANTS:
            return
        seen.add(candidate)
        variants.append({"query": candidate, "label": label, "weight": weight})

    if _is_broad_exploration_query(normalized):
        add_variant(f"{normalized} 史料记载", "史料记载", 0.97)
        add_variant(f"{normalized} 事件经过", "事件经过", 0.95)
        add_variant(f"{normalized} 背景影响", "背景影响", 0.93)

        if any(hint in normalized for hint in PERIOD_QUERY_HINTS):
            add_variant(f"{normalized} 阶段脉络", "阶段脉络", 0.92)

        for period, facets in HISTORICAL_PERIOD_FACETS.items():
            if period not in normalized:
                continue
            for facet in facets:
                add_variant(f"{facet} {normalized}", f"{period}分期:{facet}", 0.91)
                if len(variants) >= MAX_QUERY_VARIANTS:
                    break
            if len(variants) >= MAX_QUERY_VARIANTS:
                break

    return variants


def _expand_period_aliases(query: str) -> list[str]:
    aliases: list[str] = []
    for period, replacements in HISTORICAL_PERIOD_ALIASES.items():
        if period not in query:
            continue
        for replacement in replacements:
            candidate = _normalize_query_text(query.replace(period, replacement, 1))
            if candidate and candidate not in aliases:
                aliases.append(candidate)
    return aliases


def _identify_alias_term(query: str) -> str:
    for replacements in HISTORICAL_PERIOD_ALIASES.values():
        for replacement in replacements:
            if replacement in query:
                return replacement
    return query


def _rewrite_finance_facet(query: str, facet: str) -> str:
    return _normalize_query_text(
        re.sub(
            r"财政(?:情况|概况|变化|变迁|问题|状况|体制|制度)?",
            facet,
            query,
            count=1,
        )
    )


def _build_doc_id_query_variants(query: str) -> list[dict[str, str | float]]:
    normalized = _normalize_query_text(query)
    if not normalized:
        return [{"query": query, "label": "原始问题", "weight": 1.0}]

    variants: list[dict[str, str | float]] = [
        {"query": normalized, "label": "原始问题", "weight": 1.0},
    ]
    seen = {normalized}

    def add_variant(text: str, label: str, weight: float) -> None:
        candidate = _normalize_query_text(text)
        if not candidate or candidate in seen or len(variants) >= MAX_DOC_ID_QUERY_VARIANTS:
            return
        seen.add(candidate)
        variants.append({"query": candidate, "label": label, "weight": weight})

    alias_variants = _expand_period_aliases(normalized)
    for alias_query in alias_variants:
        add_variant(alias_query, f"同书别名:{_identify_alias_term(alias_query)}", 0.99)

    base_query = alias_variants[0] if alias_variants else normalized
    if "财政" in normalized and any(hint in normalized for hint in HISTORICAL_TOPIC_RETRY_HINTS):
        for facet in FINANCE_FACET_QUERIES:
            add_variant(_rewrite_finance_facet(base_query, facet), f"同书聚焦:{facet}", 0.98)

    return variants


def _select_query_variants(query: str, doc_ids: list[str] | None = None) -> list[dict[str, str | float]]:
    if not doc_ids:
        return _build_query_variants(query)
    # When the search is already narrowed to specific books, keep the query
    # anchored to the same books, but still allow a few nearby retries such as
    # period aliases and narrower topic facets.
    return _build_doc_id_query_variants(query)


SOURCE_KIND_BOOSTS = {
    "annotation": 1.30,
    "excerpt": 1.20,
    "upload": 1.10,
    "thread_upload": 1.00,
    "global_document": 0.95,
    "translation": 0.85,
}


def get_embedding_model() -> Embeddings:
    """Get the embedding model based on configuration."""
    config = get_knowledge_base_config()
    if not config.embedding:
        raise ValueError("Embedding configuration is missing")

    kwargs = {}
    if config.embedding.api_key:
        kwargs["api_key"] = config.embedding.api_key
    if config.embedding.api_base:
        kwargs["base_url"] = config.embedding.api_base

    kwargs["model"] = config.embedding.model

    # OpenRouter's embeddings endpoint accepts raw string input but does not
    # reliably handle the token-id payload shape generated by LangChain's
    # length-safe embedding path for unknown models.
    if config.embedding.api_base and "openrouter.ai" in config.embedding.api_base:
        kwargs["check_embedding_ctx_length"] = False

    return resolve_variable(config.embedding.use)(**kwargs)


def get_qdrant_client() -> QdrantClient:
    """Get the Qdrant client based on configuration."""
    config = get_knowledge_base_config()

    if config.qdrant.mode == "server":
        if not config.qdrant.url:
            raise ValueError("Qdrant URL is required for server mode")
        return QdrantClient(
            url=config.qdrant.url,
            api_key=config.qdrant.api_key,
            timeout=config.qdrant.request_timeout,
        )
    return QdrantClient(path=config.qdrant.local_path)


class KnowledgeBaseRetriever:
    """Retriever for the knowledge base."""

    def __init__(self):
        """Initialize the retriever."""
        self.config = get_knowledge_base_config()
        self.client = get_qdrant_client()
        self.embeddings = get_embedding_model()

    def _score_result(self, result: dict) -> float:
        metadata = result.get("metadata", {})
        scope = str(metadata.get("scope") or "global")
        source_kind = str(
            metadata.get("source_kind")
            or (
                "thread_upload"
                if scope == "thread"
                else "upload"
                if scope == "user"
                else "global_document"
            )
        )
        base_score = float(result.get("score", 0.0) or 0.0)
        query_variant_weight = float(result.get("query_variant_weight", 1.0) or 1.0)
        return (
            base_score
            * SCOPE_BOOSTS.get(scope, 1.0)
            * SOURCE_KIND_BOOSTS.get(source_kind, 1.0)
            * query_variant_weight
        )

    def _search_collection(
        self,
        collection_name: str,
        query: str,
        doc_ids: list[str] | None = None,
        top_k: int | None = None,
    ) -> list[dict]:
        vector_store = QdrantVectorStore(
            client=self.client,
            collection_name=collection_name,
            embedding=self.embeddings,
        )

        qdrant_filter = None
        if doc_ids:
            qdrant_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="metadata.doc_id",
                        match=models.MatchAny(any=doc_ids),
                    )
                ]
            )

        limit = top_k or self.config.retrieval.top_k
        results = vector_store.similarity_search_with_score(
            query,
            k=limit,
            filter=qdrant_filter,
            score_threshold=self.config.retrieval.score_threshold,
        )

        if not results and (self.config.retrieval.score_threshold or 0) > 0:
            # Fallback: keep the same collection/filter, but relax the threshold so
            # broad historical queries still surface candidate passages instead of
            # returning an empty tool result to the model.
            results = vector_store.similarity_search_with_score(
                query,
                k=max(limit, MIN_PER_QUERY_TOP_K * 2),
                filter=qdrant_filter,
                score_threshold=0.0,
            )

        formatted_results: list[dict] = []
        for doc, score in results:
            formatted_results.append(
                {
                    "content": doc.page_content,
                    "metadata": doc.metadata,
                    "score": score,
                    "source": doc.metadata.get("source", "Unknown"),
                    "filename": doc.metadata.get(
                        "filename",
                        doc.metadata.get("source", "").split("/")[-1],
                    ),
                    "page": doc.metadata.get("page"),
                    "source_type": doc.metadata.get("source_type", "unknown"),
                    "collection_name": collection_name,
                }
            )

        return formatted_results

    def _resolve_effective_doc_ids(
        self,
        *,
        thread_id: str | None,
        user_id: str | None,
        doc_ids: list[str] | None,
        scopes: list[str] | None,
        folder_paths: list[str] | None,
    ) -> list[str] | None:
        if not folder_paths:
            return doc_ids

        visible_entries = filter_book_catalog_entries(
            list_book_catalog(thread_id=thread_id, user_id=user_id),
            doc_ids=doc_ids,
            scopes=scopes,
            folder_paths=folder_paths,
        )
        if not visible_entries:
            return []
        return [entry.doc_id for entry in visible_entries]

    def _merge_duplicate_results(self, results: list[dict]) -> list[dict]:
        deduped: dict[tuple[str, int | None, int | None, str, str], dict] = {}
        for result in results:
            metadata = result.get("metadata", {})
            dedupe_key = (
                metadata.get("origin_doc_id")
                or metadata.get("doc_id")
                or result.get("filename", ""),
                metadata.get("pdf_page_no")
                or metadata.get("page_no")
                or metadata.get("page")
                or metadata.get("line_start"),
                metadata.get("paragraph_no_in_doc")
                or metadata.get("paragraph_no")
                or metadata.get("line_end"),
                result.get("content", ""),
                metadata.get("source_kind", ""),
            )
            existing = deduped.get(dedupe_key)
            if existing is None:
                result.setdefault("matched_queries", [])
                if result.get("matched_query") and result["matched_query"] not in result["matched_queries"]:
                    result["matched_queries"].append(result["matched_query"])
                deduped[dedupe_key] = result
                continue

            existing_queries = existing.setdefault("matched_queries", [])
            for matched_query in result.get("matched_queries") or []:
                if matched_query not in existing_queries:
                    existing_queries.append(matched_query)
            if result.get("matched_query") and result["matched_query"] not in existing_queries:
                existing_queries.append(result["matched_query"])
            if result.get("weighted_score", result.get("score", 0)) > existing.get(
                "weighted_score",
                existing.get("score", 0),
            ):
                existing.update(result)
                existing["matched_queries"] = existing_queries

        return list(deduped.values())

    def _select_diverse_results(self, results: list[dict], limit: int) -> list[dict]:
        remaining = list(results)
        selected: list[dict] = []
        seen_doc_ids: dict[str, int] = {}
        seen_titles: dict[str, int] = {}

        while remaining and len(selected) < limit:
            best_index = 0
            best_score = -1.0
            for index, candidate in enumerate(remaining):
                metadata = candidate.get("metadata", {})
                doc_id = str(metadata.get("origin_doc_id") or metadata.get("doc_id") or "")
                title = str(metadata.get("title") or candidate.get("filename") or "")
                adjusted_score = float(candidate.get("weighted_score", candidate.get("score", 0.0)) or 0.0)
                adjusted_score *= 0.9 ** seen_doc_ids.get(doc_id, 0)
                adjusted_score *= 0.95 ** seen_titles.get(title, 0)
                if adjusted_score > best_score:
                    best_index = index
                    best_score = adjusted_score

            chosen = remaining.pop(best_index)
            selected.append(chosen)
            chosen_metadata = chosen.get("metadata", {})
            chosen_doc_id = str(chosen_metadata.get("origin_doc_id") or chosen_metadata.get("doc_id") or "")
            chosen_title = str(chosen_metadata.get("title") or chosen.get("filename") or "")
            if chosen_doc_id:
                seen_doc_ids[chosen_doc_id] = seen_doc_ids.get(chosen_doc_id, 0) + 1
            if chosen_title:
                seen_titles[chosen_title] = seen_titles.get(chosen_title, 0) + 1

        return selected

    def search(
        self,
        query: str,
        thread_id: str | None = None,
        user_id: str | None = None,
        doc_ids: list[str] | None = None,
        scopes: list[str] | None = None,
        folder_paths: list[str] | None = None,
    ) -> list[dict]:
        """Search for relevant documents."""
        started_at = time.perf_counter()
        enabled_scopes = scopes or list(DEFAULT_SEARCH_SCOPES)
        effective_doc_ids = self._resolve_effective_doc_ids(
            thread_id=thread_id,
            user_id=user_id,
            doc_ids=doc_ids,
            scopes=enabled_scopes,
            folder_paths=folder_paths,
        )
        if effective_doc_ids == []:
            logger.info(
                "Knowledge search skipped: query=%r folder_paths=%s scopes=%s effective_doc_ids=0 elapsed_ms=%.1f",
                query,
                ",".join(folder_paths or []),
                ",".join(enabled_scopes),
                (time.perf_counter() - started_at) * 1000,
            )
            return []

        query_variants = _select_query_variants(query, doc_ids=effective_doc_ids)
        per_query_top_k = max(self.config.retrieval.top_k, MIN_PER_QUERY_TOP_K)
        final_limit = max(
            self.config.retrieval.top_k,
            MIN_RESULT_LIMIT if len(query_variants) > 1 or effective_doc_ids else self.config.retrieval.top_k,
        )
        collections: list[str] = []
        if user_id and "user" in enabled_scopes:
            collections.append(
                get_user_collection_name(
                    self.config.qdrant.collection_name,
                    user_id,
                ),
            )
        if thread_id:
            if "thread" in enabled_scopes:
                collections.append(
                    get_thread_collection_name(
                        self.config.qdrant.collection_name,
                        thread_id,
                    ),
                )
        if "global" in enabled_scopes:
            collections.append(self.config.qdrant.collection_name)

        merged_results: list[dict] = []
        for variant in query_variants:
            variant_query = str(variant["query"])
            variant_label = str(variant["label"])
            variant_weight = float(variant["weight"])

            for collection_name in collections:
                try:
                    vector_started_at = time.perf_counter()
                    results = self._search_collection(
                        collection_name,
                        variant_query,
                        doc_ids=effective_doc_ids,
                        top_k=per_query_top_k,
                    )
                    logger.info(
                        "Knowledge vector search: query=%r variant=%r collection=%s doc_ids=%s hits=%s elapsed_ms=%.1f",
                        query,
                        variant_label,
                        collection_name,
                        len(effective_doc_ids or []),
                        len(results),
                        (time.perf_counter() - vector_started_at) * 1000,
                    )
                except Exception:
                    logger.exception(
                        "Knowledge vector search failed: query=%r variant=%r collection=%s",
                        query,
                        variant_label,
                        collection_name,
                    )
                    continue
                for result in results:
                    result["matched_query"] = variant_label
                    result["query_variant"] = variant_query
                    result["query_variant_weight"] = variant_weight
                    merged_results.append(result)

            try:
                lexical_started_at = time.perf_counter()
                lexical_results = lexical_search_documents(
                    variant_query,
                    thread_id=thread_id,
                    user_id=user_id,
                    doc_ids=effective_doc_ids,
                    scopes=enabled_scopes,
                    top_k=per_query_top_k,
                )
                logger.info(
                    "Knowledge lexical search: query=%r variant=%r doc_ids=%s hits=%s elapsed_ms=%.1f",
                    query,
                    variant_label,
                    len(effective_doc_ids or []),
                    len(lexical_results),
                    (time.perf_counter() - lexical_started_at) * 1000,
                )
            except Exception:
                logger.exception(
                    "Knowledge lexical search failed: query=%r variant=%r",
                    query,
                    variant_label,
                )
                lexical_results = []

            for result in lexical_results:
                result["matched_query"] = variant_label
                result["query_variant"] = variant_query
                result["query_variant_weight"] = variant_weight
                merged_results.append(result)

        if not _looks_like_exact_lookup(query):
            merged_results = [
                result for result in merged_results if _is_substantive_result(result)
            ]

        for result in merged_results:
            result["weighted_score"] = self._score_result(result)

        merged_results.sort(key=lambda item: item.get("weighted_score", item.get("score", 0)), reverse=True)
        deduped_results = self._merge_duplicate_results(merged_results)
        deduped_results.sort(key=lambda item: item.get("weighted_score", item.get("score", 0)), reverse=True)
        selected = self._select_diverse_results(deduped_results, limit=final_limit)
        logger.info(
            "Knowledge search complete: query=%r variants=%s collections=%s doc_ids=%s merged=%s deduped=%s returned=%s elapsed_ms=%.1f",
            query,
            len(query_variants),
            len(collections),
            len(effective_doc_ids or []),
            len(merged_results),
            len(deduped_results),
            len(selected),
            (time.perf_counter() - started_at) * 1000,
        )
        return selected


def get_retriever() -> KnowledgeBaseRetriever:
    """Get the singleton retriever instance."""
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = KnowledgeBaseRetriever()
    return _retriever_instance
