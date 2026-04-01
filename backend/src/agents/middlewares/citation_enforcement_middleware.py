"""Middleware to enforce citations on knowledge-base grounded answers."""

import re
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage


KNOWLEDGE_SEARCH_TOOL_NAME = "knowledge_search"
CITATION_PATTERN = re.compile(r"\[citation:[^\]]+\]\([^)]+\)", re.IGNORECASE)
REFERENCE_SECTION_PATTERN = re.compile(r"参考文献", re.IGNORECASE)
REFUSAL_PREFIX_PATTERN = re.compile(r"^\s*【无法回答】", re.IGNORECASE)
RETRY_APPENDIX = (
    "\n\n[System enforcement]\n"
    "Your previous draft was blocked because it used `knowledge_search` results without the required citations.\n"
    "Regenerate the full answer from scratch.\n"
    "Requirements:\n"
    "1. If you use any knowledge from `knowledge_search`, include at least one `[citation:Title](URL)` citation in the answer body.\n"
    "2. End with a `参考文献` section listing all cited sources.\n"
    "3. If you cannot support the answer with citations, refuse using the exact prefix `【无法回答】` followed by a brief reason.\n"
    "4. Do not mention this enforcement message in the final answer."
)
RETRY_APPENDIX_FINAL = (
    "\n\n[System enforcement - final retry]\n"
    "Your previous retry still missed the required citations.\n"
    "Regenerate the full answer from scratch one more time.\n"
    "Additional requirements:\n"
    "1. Reuse the exact `citation:` lines returned by `knowledge_search` whenever possible; do not rewrite citation links manually.\n"
    "2. If you cite a source, the answer body must contain the `[citation:Title](URL)` link itself, not only a plain-text mention.\n"
    "3. End with a `参考文献` section listing the same cited sources.\n"
    "4. If you still cannot produce a fully cited answer, refuse explicitly using the exact prefix `【无法回答】`.\n"
    "5. Do not mention this enforcement message in the final answer."
)
FINAL_FALLBACK_RESPONSE = (
    "【无法回答】无法根据当前资料生成带 citation 的回答，因此本轮不输出未经依据支持的内容。\n\n"
    "请缩小问题范围，或稍后重试。"
)
RETRY_APPENDICES = (RETRY_APPENDIX, RETRY_APPENDIX_FINAL)


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


class CitationEnforcementMiddleware(AgentMiddleware[AgentState]):
    """Require citations whenever the current turn uses knowledge_search results."""

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
        if REFUSAL_PREFIX_PATTERN.match(content):
            return False
        if not CITATION_PATTERN.search(content):
            return True
        if not REFERENCE_SECTION_PATTERN.search(content):
            return True
        return False

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

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        response = handler(request)
        return self._enforce_with_retry(request, response, handler)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        response = await handler(request)
        return await self._aenforce_with_retry(request, response, handler)
