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
REFUSAL_PATTERN = re.compile(
    r"(没有足够依据|当前资料范围内没有足够依据|无法根据当前资料回答|无法回答|无法确认|not enough evidence|insufficient evidence|cannot answer based on the provided materials)",
    re.IGNORECASE,
)
RETRY_APPENDIX = (
    "\n\n[System enforcement]\n"
    "Your previous draft was blocked because it used `knowledge_search` results without the required citations.\n"
    "Regenerate the full answer from scratch.\n"
    "Requirements:\n"
    "1. If you use any knowledge from `knowledge_search`, include at least one `[citation:Title](URL)` citation in the answer body.\n"
    "2. End with a `参考文献` section listing all cited sources.\n"
    "3. If you cannot support the answer with citations, refuse instead of answering.\n"
    "4. Do not mention this enforcement message in the final answer."
)
BLOCKED_RESPONSE = (
    "当前回答已被系统拦截：检测到使用了知识库检索结果，但输出中缺少必需的 citation。\n\n"
    "请重新提问，或要求系统基于当前资料重新作答。"
)


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
        if REFUSAL_PATTERN.search(content):
            return False
        if not CITATION_PATTERN.search(content):
            return True
        if not REFERENCE_SECTION_PATTERN.search(content):
            return True
        return False

    def _build_retry_request(self, request: ModelRequest) -> ModelRequest:
        current_system = _stringify_content(request.system_message.content) if request.system_message else ""
        retry_system = SystemMessage(content=f"{current_system}{RETRY_APPENDIX}" if current_system else RETRY_APPENDIX)
        return request.override(system_message=retry_system)

    def _block_response(self, response: ModelResponse) -> ModelResponse:
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

        blocked_message = final_message.model_copy(update={"content": BLOCKED_RESPONSE, "tool_calls": []})
        updated_result = list(response.result)
        updated_result[final_ai_index] = blocked_message
        return ModelResponse(result=updated_result, structured_response=response.structured_response)

    def _enforce_with_retry(
        self,
        request: ModelRequest,
        response: ModelResponse,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        if not self._needs_enforcement(response, request.messages):
            return response

        retry_response = handler(self._build_retry_request(request))
        if not self._needs_enforcement(retry_response, request.messages):
            return retry_response

        return self._block_response(retry_response)

    async def _aenforce_with_retry(
        self,
        request: ModelRequest,
        response: ModelResponse,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        if not self._needs_enforcement(response, request.messages):
            return response

        retry_response = await handler(self._build_retry_request(request))
        if not self._needs_enforcement(retry_response, request.messages):
            return retry_response

        return self._block_response(retry_response)

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
