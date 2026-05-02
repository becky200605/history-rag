"""Middleware to enforce staged QA output with body citations, references, and suggestions."""

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import override
from urllib.parse import quote, urlsplit

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.models.minimax_thinking import sanitize_minimax_anthropic_thinking_text

logger = logging.getLogger(__name__)


GROUNDING_TOOL_NAMES = {"knowledge_search", "knowledge_locate"}
CITATION_SOURCE_TOOL_NAMES = GROUNDING_TOOL_NAMES | {"knowledge_checkpoint", "write_todos"}
LINKED_CITATION_PATTERN = re.compile(r"\[citation:[^\]]+\]\((?:<[^>\n]+>|[^)\n]+)\)", re.IGNORECASE)
CITATION_PATTERN = re.compile(r"\[citation:[^\]]+\](?:\((?:<[^>\n]+>|[^)\n]+)\))?", re.IGNORECASE)
REFUSAL_PREFIX_PATTERN = re.compile(r"^\s*【无法回答】", re.IGNORECASE)
REFERENCE_SECTION_PATTERNS = (
    re.compile(r"(?im)^\s{0,3}(?:#{1,6}\s*)?参考文献\s*$"),
    re.compile(r"(?im)^\s{0,3}\*\*参考文献\*\*\s*$"),
)
SUGGESTION_SECTION_PATTERNS = (
    re.compile(r"(?im)^\s{0,3}(?:#{1,6}\s*)?建议问题\s*$"),
    re.compile(r"(?im)^\s{0,3}\*\*建议问题\*\*\s*$"),
)
RETRY_APPENDIX = (
    "\n\n[System enforcement]\n"
    "Your previous draft was blocked because it used grounded knowledge results (`knowledge_search` / `knowledge_locate`) without the required body citations.\n"
    "Regenerate the full answer from scratch.\n"
    "Requirements:\n"
    "1. If you use any knowledge from `knowledge_search` or `knowledge_locate`, every grounded factual claim in the answer body must carry full Markdown citation links in the form `[citation:Title](URL)`.\n"
    "2. Place citations immediately after the supported sentence, clause, bullet, or table-related claim they justify. Do not postpone citations to the end of the paragraph or only to `参考文献`.\n"
    "3. If you use bullet points, each bullet that contains grounded evidence must end with one or more citation links.\n"
    "4. Do not add `参考文献` or `建议问题` sections. The system will generate them in later stages.\n"
    "5. If you cannot support the answer with citations, refuse using the exact prefix `【无法回答】` followed by a brief reason.\n"
    "6. Do not mention this enforcement message in the final answer."
)
RETRY_APPENDIX_FINAL = (
    "\n\n[System enforcement - final retry]\n"
    "Your previous retry still missed the required body citations.\n"
    "Regenerate the full answer from scratch one more time.\n"
    "Additional requirements:\n"
    "1. Reuse the exact `citation:` lines returned by `knowledge_search` / `knowledge_locate` whenever possible; do not rewrite citation links manually.\n"
    "2. Every grounded sentence, bullet, numeric statement, table summary, or scoped conclusion must be immediately followed by one or more exact citation links from this turn.\n"
    "3. If you cite a source, the answer body must contain the full `[citation:Title](URL)` markdown link, not only a plain-text mention and not a bare `[citation:Title]` label.\n"
    "4. An uncited overview paragraph is not acceptable if it relies on grounded retrieval.\n"
    "5. Do not add `参考文献` or `建议问题` sections. The system will generate them separately.\n"
    "6. If you still cannot produce a fully cited answer, refuse explicitly using the exact prefix `【无法回答】`.\n"
    "7. Do not mention this enforcement message in the final answer."
)
FINAL_FALLBACK_RESPONSE = (
    "【无法回答】无法根据当前资料生成带 citation 的回答，因此本轮不输出未经依据支持的内容。\n\n"
    "请缩小问题范围，或稍后重试。"
)
RETRY_APPENDICES = (RETRY_APPENDIX, RETRY_APPENDIX_FINAL)
SUGGESTION_SYSTEM_PROMPT = (
    "你负责回答链路中的第 3 阶段：生成建议问题。\n"
    "输入会包含用户原问题、阶段 1 的回答正文，以及阶段 2 的参考文献信息（如果有）。\n"
    "请只输出 3 行建议问题，每行一个问题，不要输出标题、解释、前言、后记、代码块或额外编号说明。\n"
    "要求：\n"
    "1. 必须与当前问题和当前回答高度相关。\n"
    "2. 必须帮助用户继续追问到更深一层，而不是泛泛而谈。\n"
    "3. 如果阶段 1 是 `【无法回答】`，问题应引导用户缩小范围、补充线索、指定材料或切换到更可检索的角度。\n"
    "4. 默认使用与用户相同的语言。"
)
SUGGESTION_HEADING_PATTERN = re.compile(r"^(?:#{1,6}\s*|\*\*)?建议问题(?:\*\*)?\s*$", re.IGNORECASE)
QUESTION_PREFIX_PATTERN = re.compile(r"^\s*(?:[-*•]|\d+[.)]|[一二三四五六七八九十]+[、.])\s*")


def _stringify_content(content: object) -> str:
    if isinstance(content, str):
        return sanitize_minimax_anthropic_thinking_text(content).content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(sanitize_minimax_anthropic_thinking_text(str(item.get("text", ""))).content)
            elif isinstance(item, dict) and item.get("type") in {"thinking", "redacted_thinking"}:
                continue
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content or "")


def _latest_human_index(messages: list) -> int:
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return index
    return 0


def _latest_human_message(messages: list) -> str:
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return _stringify_content(messages[index].content).strip()
    return ""


def _find_first_section_start(content: str) -> int | None:
    matches = []
    for pattern in (*REFERENCE_SECTION_PATTERNS, *SUGGESTION_SECTION_PATTERNS):
        match = pattern.search(content)
        if match:
            matches.append(match.start())
    return min(matches) if matches else None


def _strip_generated_sections(content: str) -> str:
    start = _find_first_section_start(content)
    if start is None:
        return content.strip()
    return content[:start].rstrip()


def _extract_citations(content: str) -> list[str]:
    seen: set[str] = set()
    citations: list[str] = []
    for citation in CITATION_PATTERN.findall(content):
        normalized_citation = _normalize_citation_markdown(citation)
        if not _is_valid_citation_markdown(normalized_citation):
            continue
        if normalized_citation in seen:
            continue
        seen.add(normalized_citation)
        citations.append(normalized_citation)
    return citations


def _tool_message_contains_citations(message: ToolMessage) -> bool:
    return bool(LINKED_CITATION_PATTERN.search(_stringify_content(message.content)))


def _citation_label(citation: str) -> str:
    if "](" in citation:
        return citation.split("](", 1)[0] + "]"
    return citation


def _extract_citation_inner_label(citation: str) -> str:
    match = re.match(r"\[citation:([^\]]+)\](?:\([^)]+\))?", citation, re.IGNORECASE)
    return match.group(1).strip() if match else citation.strip()


def _extract_citation_url(citation: str) -> str | None:
    match = re.match(r"\[citation:[^\]]+\]\((<[^>\n]+>|[^)\n]+)\)", citation, re.IGNORECASE)
    if not match:
        return None
    url = match.group(1).strip()
    if url.startswith("<") and url.endswith(">"):
        url = url[1:-1].strip()
    return url or None


def _normalize_internal_citation_url(url: str | None) -> str | None:
    if not url:
        return None
    if url.startswith("/api/knowledge/docs/") or url.startswith("/api/secure-knowledge/users/me/knowledge/docs/"):
        return quote(url, safe="/:?=&%#")
    return url


def _normalize_citation_markdown(citation: str) -> str:
    url = _extract_citation_url(citation)
    normalized_url = _normalize_internal_citation_url(url)
    if not url or not normalized_url or normalized_url == url:
        return citation
    wrapped_url = f"<{normalized_url}>" if "<" in citation else normalized_url
    return re.sub(
        r"\((<[^>\n]+>|[^)\n]+)\)$",
        f"({wrapped_url})",
        citation,
        count=1,
    )


def _is_valid_citation_url(url: str | None) -> bool:
    if not url:
        return False
    if re.match(r"^citations?:", url, re.IGNORECASE):
        return False

    normalized_url = _normalize_internal_citation_url(url)
    if normalized_url is None:
        return False
    if re.search(r"\s", normalized_url):
        return False

    if normalized_url.startswith("/"):
        try:
            parts = urlsplit(normalized_url)
        except Exception:
            return False
        return bool(parts.path)

    try:
        parts = urlsplit(normalized_url)
    except Exception:
        return False
    return parts.scheme in {"http", "https"} and bool(parts.netloc)


def _is_valid_citation_markdown(citation: str) -> bool:
    url = _extract_citation_url(citation)
    return _is_valid_citation_url(url)


def _normalize_citation_text(text: str) -> str:
    translated = text.translate(str.maketrans({"（": "(", "）": ")", "：": ":", "　": " "}))
    return re.sub(r"\s+", "", translated).strip().lower()


def _extract_location_parts(label: str) -> tuple[str, int | None, int | None, int | None]:
    normalized = label.translate(str.maketrans({"（": "(", "）": ")", "：": ":"}))
    title = normalized
    page_no = None
    pdf_page_no = None
    paragraph_no = None

    location_match = re.search(r"(原书第\s*\d+\s*页|PDF第\s*\d+\s*页)", normalized, re.IGNORECASE)
    if location_match:
        title = normalized[: location_match.start()].strip()

    page_match = re.search(r"原书第\s*(\d+)\s*页", normalized, re.IGNORECASE)
    if page_match:
        page_no = int(page_match.group(1))

    pdf_page_match = re.search(r"PDF第\s*(\d+)\s*页", normalized, re.IGNORECASE)
    if pdf_page_match:
        pdf_page_no = int(pdf_page_match.group(1))

    paragraph_match = re.search(r"第\s*(\d+)\s*段", normalized, re.IGNORECASE)
    if paragraph_match:
        paragraph_no = int(paragraph_match.group(1))

    return title, page_no, pdf_page_no, paragraph_no


@dataclass(frozen=True)
class _CitationCandidate:
    label: str
    full_citation: str
    normalized_label: str
    normalized_title: str
    page_no: int | None
    pdf_page_no: int | None
    paragraph_no: int | None


def _build_citation_candidates(messages: list) -> list[_CitationCandidate]:
    start = _latest_human_index(messages)
    candidates: list[_CitationCandidate] = []
    seen: set[str] = set()
    for message in messages[start:]:
        if not isinstance(message, ToolMessage) or getattr(message, "name", None) not in CITATION_SOURCE_TOOL_NAMES:
            continue
        content = _stringify_content(message.content)
        for citation in LINKED_CITATION_PATTERN.findall(content):
            label = _extract_citation_inner_label(citation)
            normalized_label = _normalize_citation_text(label)
            if normalized_label in seen:
                continue
            seen.add(normalized_label)
            title, page_no, pdf_page_no, paragraph_no = _extract_location_parts(label)
            candidates.append(
                _CitationCandidate(
                    label=label,
                    full_citation=citation,
                    normalized_label=normalized_label,
                    normalized_title=_normalize_citation_text(title),
                    page_no=page_no,
                    pdf_page_no=pdf_page_no,
                    paragraph_no=paragraph_no,
                )
            )
    return candidates


def _available_citation_lines(messages: list) -> list[str]:
    return [f"citation: {candidate.full_citation}" for candidate in _build_citation_candidates(messages)]


def _resolve_citation_from_candidates(citation: str, messages: list) -> str | None:
    label = _extract_citation_inner_label(citation)
    normalized_label = _normalize_citation_text(label)
    candidates = _build_citation_candidates(messages)
    if not candidates:
        return None

    for candidate in candidates:
        if candidate.normalized_label == normalized_label:
            return candidate.full_citation

    title, page_no, pdf_page_no, paragraph_no = _extract_location_parts(label)
    normalized_title = _normalize_citation_text(title)
    scored: list[tuple[float, _CitationCandidate]] = []
    for candidate in candidates:
        score = 0.0
        if normalized_title and candidate.normalized_title:
            if normalized_title == candidate.normalized_title:
                score += 100
            elif normalized_title in candidate.normalized_title or candidate.normalized_title in normalized_title:
                score += 80
            else:
                score += SequenceMatcher(None, normalized_title, candidate.normalized_title).ratio() * 40

        if page_no is not None and candidate.page_no == page_no:
            score += 20
        if pdf_page_no is not None and candidate.pdf_page_no == pdf_page_no:
            score += 15
        if paragraph_no is not None and candidate.paragraph_no == paragraph_no:
            score += 20
        scored.append((score, candidate))

    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored or scored[0][0] < 70:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 5:
        return None
    return scored[0][1].full_citation


def _consume_optional_markdown_link_target(text: str, start_index: int) -> int:
    index = start_index
    while index < len(text) and text[index] in {" ", "\t"}:
        index += 1
    if index >= len(text) or text[index] != "(":
        return start_index

    index += 1
    if index < len(text) and text[index] == "<":
        while index < len(text) and text[index] not in {">", "\n"}:
            index += 1
        if index < len(text) and text[index] == ">":
            index += 1
        if index < len(text) and text[index] == ")":
            index += 1
        return index

    depth = 1
    while index < len(text):
        char = text[index]
        if char == "\n":
            break
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                index += 1
                return index
        index += 1
    return index


def _replace_exact_candidate_mentions(answer_body: str, candidates: list[_CitationCandidate]) -> str:
    repaired_body = answer_body
    for candidate in candidates:
        label_token = f"[citation:{candidate.label}]"
        if label_token not in repaired_body:
            continue

        parts: list[str] = []
        cursor = 0
        label_length = len(label_token)
        while True:
            match_index = repaired_body.find(label_token, cursor)
            if match_index < 0:
                parts.append(repaired_body[cursor:])
                break
            parts.append(repaired_body[cursor:match_index])
            end_index = _consume_optional_markdown_link_target(
                repaired_body,
                match_index + label_length,
            )
            if end_index == match_index + label_length:
                end_index = match_index + label_length
            parts.append(candidate.full_citation)
            cursor = end_index

        repaired_body = "".join(parts)
    return repaired_body


def _normalize_answer_citations(answer_body: str, messages: list) -> str:
    candidates = _build_citation_candidates(messages)
    candidate_set = {candidate.full_citation for candidate in candidates}
    repaired_body = _replace_exact_candidate_mentions(answer_body, candidates) if candidates else answer_body

    def _replace(match: re.Match[str]) -> str:
        citation = match.group(0)
        normalized_citation = _normalize_citation_markdown(citation)
        if normalized_citation in candidate_set:
            return normalized_citation
        resolved = _resolve_citation_from_candidates(citation, messages)
        if resolved:
            return resolved
        if _is_valid_citation_markdown(normalized_citation):
            return normalized_citation
        return ""

    return CITATION_PATTERN.sub(_replace, repaired_body)


def _has_supported_body_citation(answer_body: str, messages: list) -> bool:
    citations = _extract_citations(answer_body)
    if not citations:
        return False

    candidates = _build_citation_candidates(messages)
    if not candidates:
        return True

    candidate_set = {candidate.full_citation for candidate in candidates}
    for citation in citations:
        if citation in candidate_set:
            return True
        if _resolve_citation_from_candidates(citation, messages):
            return True
    return False


def _build_reference_section(answer_body: str) -> str:
    citations = _extract_citations(answer_body)
    if not citations:
        return ""
    lines = ["参考文献"]
    lines.extend(f"{index}. {citation}" for index, citation in enumerate(citations, start=1))
    return "\n".join(lines)


def _is_refusal(content: str) -> bool:
    return bool(REFUSAL_PREFIX_PATTERN.match(content.strip()))


def _normalize_question_text(text: str) -> str:
    cleaned = QUESTION_PREFIX_PATTERN.sub("", text.strip())
    return cleaned.strip(" \t\"'`")


def _question_seed(user_question: str) -> str:
    seed = " ".join(user_question.split())
    if len(seed) > 36:
        return f"{seed[:33]}..."
    return seed or "当前主题"


def _fallback_suggested_questions(*, user_question: str, refusal: bool) -> list[str]:
    seed = _question_seed(user_question)
    if refusal:
        return [
            f"能否把“{seed}”缩小到更具体的时期、人物、制度或事件后再检索？",
            f"如果指定一本相关书、一个章节名或一组关键词，是否更容易继续回答“{seed}”？",
            f"围绕“{seed}”，下一步最值得优先核实的史料线索是什么？",
        ]
    return [
        f"围绕“{seed}”，下一步最值得继续展开的关键阶段或专题是什么？",
        f"如果继续深挖“{seed}”，最需要补充证据的机制、人物或制度是哪一项？",
        f"基于“{seed}”，还有哪个对比视角或史料视角值得继续追问？",
    ]


def _normalize_suggested_questions(*, text: str, user_question: str, refusal: bool) -> list[str]:
    seen: set[str] = set()
    questions: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if SUGGESTION_HEADING_PATTERN.match(line):
            continue
        normalized = _normalize_question_text(sanitize_minimax_anthropic_thinking_text(line).content)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        questions.append(normalized)

    for fallback in _fallback_suggested_questions(user_question=user_question, refusal=refusal):
        if len(questions) >= 3:
            break
        if fallback in seen:
            continue
        seen.add(fallback)
        questions.append(fallback)

    return questions[:3]


def _build_suggestion_prompt(*, user_question: str, answer_body: str, reference_section: str) -> str:
    references = reference_section or "（本轮无参考文献阶段内容）"
    return (
        f"用户原问题：\n{user_question or '（未提供）'}\n\n"
        f"阶段1-回答正文：\n{answer_body or '（空）'}\n\n"
        f"阶段2-参考文献：\n{references}"
    )


class CitationEnforcementMiddleware(AgentMiddleware[AgentState]):
    """Require body citations for grounded answers, then assemble references and suggestions."""

    def _turn_used_grounding_tools(self, messages: list) -> bool:
        start = _latest_human_index(messages)
        for message in messages[start:]:
            if not isinstance(message, ToolMessage):
                continue
            tool_name = getattr(message, "name", None)
            if tool_name in GROUNDING_TOOL_NAMES:
                return True
            if tool_name == "write_todos" and _tool_message_contains_citations(message):
                return True
        return False

    def _needs_enforcement(self, response: ModelResponse, messages: list) -> bool:
        if not self._turn_used_grounding_tools(messages):
            return False

        ai_messages = [message for message in response.result if isinstance(message, AIMessage)]
        if not ai_messages:
            return False

        final_message = ai_messages[-1]
        if final_message.tool_calls:
            return False

        content = _stringify_content(final_message.content)
        answer_body = _normalize_answer_citations(_strip_generated_sections(content), messages)
        if _is_refusal(answer_body):
            return False
        return not _has_supported_body_citation(answer_body, messages)

    def _build_retry_request(self, request: ModelRequest, appendix: str) -> ModelRequest:
        current_system = _stringify_content(request.system_message.content) if request.system_message else ""
        available_citations = _available_citation_lines(request.messages)
        citation_hint = ""
        if available_citations:
            joined = "\n".join(f"- {line}" for line in available_citations)
            citation_hint = (
                "\n\nAvailable citation lines from this turn. Copy these exact markdown links into the answer body:\n"
                f"{joined}\n"
                "Use them inline, immediately after the factual sentence, bullet, or table-related claim they support."
            )
        retry_system = SystemMessage(
            content=f"{current_system}{appendix}{citation_hint}" if current_system else f"{appendix}{citation_hint}"
        )
        return request.override(system_message=retry_system)

    def _fallback_response(self, response: ModelResponse) -> ModelResponse:
        final_ai_index = None
        final_message = None
        for index in range(len(response.result) - 1, -1, -1):
            message = response.result[index]
            if isinstance(message, AIMessage):
                final_ai_index = index
                final_message = message
                break

        if final_ai_index is None or final_message is None:
            return response

        fallback_message = final_message.model_copy(update={"content": FINAL_FALLBACK_RESPONSE, "tool_calls": []})
        updated_result = list(response.result)
        updated_result[final_ai_index] = fallback_message
        return ModelResponse(result=updated_result, structured_response=response.structured_response)

    def _enforce_with_retry(
        self,
        request: ModelRequest,
        response: ModelResponse,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        if not self._needs_enforcement(response, request.messages):
            return response

        retry_request = request
        retry_response = response
        for appendix in RETRY_APPENDICES:
            retry_request = self._build_retry_request(retry_request, appendix)
            retry_response = handler(retry_request)
            if not self._needs_enforcement(retry_response, request.messages):
                return retry_response

        return self._fallback_response(retry_response)

    async def _aenforce_with_retry(
        self,
        request: ModelRequest,
        response: ModelResponse,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        if not self._needs_enforcement(response, request.messages):
            return response

        retry_request = request
        retry_response = response
        for appendix in RETRY_APPENDICES:
            retry_request = self._build_retry_request(retry_request, appendix)
            retry_response = await handler(retry_request)
            if not self._needs_enforcement(retry_response, request.messages):
                return retry_response

        return self._fallback_response(retry_response)

    def _generate_suggested_questions_sync(
        self,
        *,
        request: ModelRequest,
        user_question: str,
        answer_body: str,
        reference_section: str,
    ) -> list[str]:
        refusal = _is_refusal(answer_body)
        model = getattr(request, "model", None)
        if model is None or not hasattr(model, "invoke"):
            return _fallback_suggested_questions(user_question=user_question, refusal=refusal)

        try:
            result = model.invoke(
                [
                    SystemMessage(content=SUGGESTION_SYSTEM_PROMPT),
                    HumanMessage(
                        content=_build_suggestion_prompt(
                            user_question=user_question,
                            answer_body=answer_body,
                            reference_section=reference_section,
                        )
                    ),
                ]
            )
            return _normalize_suggested_questions(
                text=_stringify_content(getattr(result, "content", result)),
                user_question=user_question,
                refusal=refusal,
            )
        except Exception as exc:  # pragma: no cover - defensive path
            logger.warning("Failed to generate suggested questions synchronously: %s", exc)
            return _fallback_suggested_questions(user_question=user_question, refusal=refusal)

    async def _generate_suggested_questions_async(
        self,
        *,
        request: ModelRequest,
        user_question: str,
        answer_body: str,
        reference_section: str,
    ) -> list[str]:
        refusal = _is_refusal(answer_body)
        model = getattr(request, "model", None)
        if model is None or not hasattr(model, "ainvoke"):
            return self._generate_suggested_questions_sync(
                request=request,
                user_question=user_question,
                answer_body=answer_body,
                reference_section=reference_section,
            )

        try:
            result = await model.ainvoke(
                [
                    SystemMessage(content=SUGGESTION_SYSTEM_PROMPT),
                    HumanMessage(
                        content=_build_suggestion_prompt(
                            user_question=user_question,
                            answer_body=answer_body,
                            reference_section=reference_section,
                        )
                    ),
                ]
            )
            return _normalize_suggested_questions(
                text=_stringify_content(getattr(result, "content", result)),
                user_question=user_question,
                refusal=refusal,
            )
        except Exception as exc:  # pragma: no cover - defensive path
            logger.warning("Failed to generate suggested questions asynchronously: %s", exc)
            return _fallback_suggested_questions(user_question=user_question, refusal=refusal)

    def _compose_content_sync(self, request: ModelRequest, content: str) -> str:
        answer_body = _normalize_answer_citations(_strip_generated_sections(content), request.messages)
        if not answer_body:
            return content

        reference_section = "" if _is_refusal(answer_body) else _build_reference_section(answer_body)
        suggestions = self._generate_suggested_questions_sync(
            request=request,
            user_question=_latest_human_message(request.messages),
            answer_body=answer_body,
            reference_section=reference_section,
        )

        parts = [answer_body]
        if reference_section:
            parts.append(reference_section)
        if suggestions:
            parts.append("建议问题\n" + "\n".join(f"{index}. {question}" for index, question in enumerate(suggestions, start=1)))
        return "\n\n".join(parts)

    async def _compose_content_async(self, request: ModelRequest, content: str) -> str:
        answer_body = _normalize_answer_citations(_strip_generated_sections(content), request.messages)
        if not answer_body:
            return content

        reference_section = "" if _is_refusal(answer_body) else _build_reference_section(answer_body)
        suggestions = await self._generate_suggested_questions_async(
            request=request,
            user_question=_latest_human_message(request.messages),
            answer_body=answer_body,
            reference_section=reference_section,
        )

        parts = [answer_body]
        if reference_section:
            parts.append(reference_section)
        if suggestions:
            parts.append("建议问题\n" + "\n".join(f"{index}. {question}" for index, question in enumerate(suggestions, start=1)))
        return "\n\n".join(parts)

    def _compose_response_sync(self, request: ModelRequest, response: ModelResponse) -> ModelResponse:
        final_ai_index = None
        final_message = None
        for index in range(len(response.result) - 1, -1, -1):
            message = response.result[index]
            if isinstance(message, AIMessage):
                final_ai_index = index
                final_message = message
                break

        if final_ai_index is None or final_message is None or final_message.tool_calls:
            return response

        composed_content = self._compose_content_sync(request, _stringify_content(final_message.content))
        updated_result = list(response.result)
        updated_result[final_ai_index] = final_message.model_copy(update={"content": composed_content})
        return ModelResponse(result=updated_result, structured_response=response.structured_response)

    async def _compose_response_async(self, request: ModelRequest, response: ModelResponse) -> ModelResponse:
        final_ai_index = None
        final_message = None
        for index in range(len(response.result) - 1, -1, -1):
            message = response.result[index]
            if isinstance(message, AIMessage):
                final_ai_index = index
                final_message = message
                break

        if final_ai_index is None or final_message is None or final_message.tool_calls:
            return response

        composed_content = await self._compose_content_async(request, _stringify_content(final_message.content))
        updated_result = list(response.result)
        updated_result[final_ai_index] = final_message.model_copy(update={"content": composed_content})
        return ModelResponse(result=updated_result, structured_response=response.structured_response)

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        response = handler(request)
        enforced_response = self._enforce_with_retry(request, response, handler)
        return self._compose_response_sync(request, enforced_response)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        response = await handler(request)
        enforced_response = await self._aenforce_with_retry(request, response, handler)
        return await self._compose_response_async(request, enforced_response)
