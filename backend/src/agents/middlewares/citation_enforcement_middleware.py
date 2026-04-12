"""Middleware to enforce staged QA output with body citations, references, and suggestions."""

import logging
import re
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

logger = logging.getLogger(__name__)


KNOWLEDGE_SEARCH_TOOL_NAME = "knowledge_search"
CITATION_PATTERN = re.compile(r"\[citation:[^\]]+\]\([^)]+\)", re.IGNORECASE)
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
    "Your previous draft was blocked because it used `knowledge_search` results without the required body citations.\n"
    "Regenerate the full answer from scratch.\n"
    "Requirements:\n"
    "1. If you use any knowledge from `knowledge_search`, include at least one `[citation:Title](URL)` citation in the answer body.\n"
    "2. Do not add `参考文献` or `建议问题` sections. The system will generate them in later stages.\n"
    "3. If you cannot support the answer with citations, refuse using the exact prefix `【无法回答】` followed by a brief reason.\n"
    "4. Do not mention this enforcement message in the final answer."
)
RETRY_APPENDIX_FINAL = (
    "\n\n[System enforcement - final retry]\n"
    "Your previous retry still missed the required body citations.\n"
    "Regenerate the full answer from scratch one more time.\n"
    "Additional requirements:\n"
    "1. Reuse the exact `citation:` lines returned by `knowledge_search` whenever possible; do not rewrite citation links manually.\n"
    "2. If you cite a source, the answer body must contain the `[citation:Title](URL)` link itself, not only a plain-text mention.\n"
    "3. Do not add `参考文献` or `建议问题` sections. The system will generate them separately.\n"
    "4. If you still cannot produce a fully cited answer, refuse explicitly using the exact prefix `【无法回答】`.\n"
    "5. Do not mention this enforcement message in the final answer."
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
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
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
        if citation in seen:
            continue
        seen.add(citation)
        citations.append(citation)
    return citations


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
        normalized = _normalize_question_text(line)
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

    def _turn_used_knowledge_search(self, messages: list) -> bool:
        start = _latest_human_index(messages)
        for message in messages[start:]:
            if isinstance(message, ToolMessage) and getattr(message, "name", None) == KNOWLEDGE_SEARCH_TOOL_NAME:
                return True
        return False

    def _needs_enforcement(self, response: ModelResponse, messages: list) -> bool:
        if not self._turn_used_knowledge_search(messages):
            return False

        ai_messages = [message for message in response.result if isinstance(message, AIMessage)]
        if not ai_messages:
            return False

        final_message = ai_messages[-1]
        if final_message.tool_calls:
            return False

        content = _stringify_content(final_message.content)
        answer_body = _strip_generated_sections(content)
        if _is_refusal(answer_body):
            return False
        return not CITATION_PATTERN.search(answer_body)

    def _build_retry_request(self, request: ModelRequest, appendix: str) -> ModelRequest:
        current_system = _stringify_content(request.system_message.content) if request.system_message else ""
        retry_system = SystemMessage(content=f"{current_system}{appendix}" if current_system else appendix)
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
        answer_body = _strip_generated_sections(content)
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
        answer_body = _strip_generated_sections(content)
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
