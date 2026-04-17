"""Compress old knowledge tool outputs and enforce checkpoint cadence."""

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

GROUNDING_TOOL_NAMES = {"knowledge_search", "knowledge_locate"}
CHECKPOINT_TOOL_NAME = "knowledge_checkpoint"
CHECKPOINT_ENFORCEMENT_THRESHOLD = 5
NON_SUBSTANTIVE_MARKERS = (
    "本轮没有命中到可直接使用的内部知识片段",
    "no matching page/paragraph/line context found",
    "no likely books found for this query",
    "当前对话已限定在所选资料范围内，但这些资料里没有找到匹配的候选书目",
)
CHECKPOINT_RETRY_APPENDICES = (
    "\n\n[System checkpoint enforcement]\n"
    "This turn has already accumulated multiple substantive grounded retrieval results "
    "from `knowledge_search` / `knowledge_locate` without a new `knowledge_checkpoint`.\n"
    "Your NEXT action must be exactly one call to `knowledge_checkpoint`.\n"
    "Do not call any other tool yet.\n"
    "Do not draft the final answer yet.\n"
    "Write the checkpoint so it faithfully preserves the finished retrieval block, "
    "the exact citation lines worth reusing, and any remaining gaps.\n",
    "\n\n[System checkpoint enforcement - final retry]\n"
    "You still did not call `knowledge_checkpoint`.\n"
    "Retry now and make your NEXT action exactly one `knowledge_checkpoint` tool call.\n"
    "Do not call `knowledge_search`, `knowledge_locate`, or any other tool in this step.\n"
    "Do not answer the user directly in this step.\n",
)

logger = logging.getLogger(__name__)


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


class KnowledgeCheckpointMiddleware(AgentMiddleware[AgentState]):
    """Hide old grounding payloads and push the model to checkpoint before moving on."""

    def _extract_messages_from_state(self, state: object) -> list:
        if isinstance(state, dict):
            messages = state.get("messages")
            return messages if isinstance(messages, list) else []
        messages = getattr(state, "messages", None)
        return messages if isinstance(messages, list) else []

    def _latest_human_index(self, messages: list) -> int:
        for index in range(len(messages) - 1, -1, -1):
            if isinstance(messages[index], HumanMessage):
                return index
        return -1

    def _latest_checkpoint_index(self, messages: list) -> int:
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if isinstance(message, ToolMessage) and getattr(message, "name", None) == CHECKPOINT_TOOL_NAME:
                return index
        return -1

    def _build_patched_messages(self, messages: list) -> list | None:
        last_checkpoint_index = self._latest_checkpoint_index(messages)
        if last_checkpoint_index < 0:
            return None

        patched: list = []
        changed = False
        for index, message in enumerate(messages):
            if (
                index < last_checkpoint_index
                and isinstance(message, ToolMessage)
                and getattr(message, "name", None) in GROUNDING_TOOL_NAMES
            ):
                placeholder = f"【已调用{message.name}工具】该原始检索结果已由后续 knowledge_checkpoint 检查点压缩。"
                if _stringify_content(message.content) != placeholder:
                    changed = True
                    patched.append(message.model_copy(update={"content": placeholder}))
                    continue
            patched.append(message)

        return patched if changed else None

    def _enforcement_start_index(self, messages: list) -> int:
        return max(self._latest_human_index(messages), self._latest_checkpoint_index(messages))

    def _is_substantive_grounding_message(self, message: ToolMessage) -> bool:
        if getattr(message, "name", None) not in GROUNDING_TOOL_NAMES:
            return False

        content = _stringify_content(message.content).strip()
        if not content or content.startswith("【已调用"):
            return False

        lowered = content.lower()
        return not any(marker in content or marker in lowered for marker in NON_SUBSTANTIVE_MARKERS)

    def _grounding_count_since_checkpoint(self, messages: list) -> int:
        start = self._enforcement_start_index(messages)
        count = 0
        for message in messages[start + 1 :]:
            if isinstance(message, ToolMessage) and self._is_substantive_grounding_message(message):
                count += 1
        return count

    def _needs_checkpoint_enforcement(self, messages: list) -> bool:
        return self._grounding_count_since_checkpoint(messages) >= CHECKPOINT_ENFORCEMENT_THRESHOLD

    def _response_calls_checkpoint(self, response: ModelResponse) -> bool:
        ai_messages = [message for message in response.result if isinstance(message, AIMessage)]
        if not ai_messages:
            return False

        final_message = ai_messages[-1]
        if not final_message.tool_calls:
            return False

        tool_names = [tool_call.get("name") for tool_call in final_message.tool_calls]
        return bool(tool_names) and all(name == CHECKPOINT_TOOL_NAME for name in tool_names)

    def _build_retry_request(self, request: ModelRequest, appendix: str) -> ModelRequest:
        current_system = _stringify_content(request.system_message.content) if request.system_message else ""
        retry_system = SystemMessage(content=f"{current_system}{appendix}" if current_system else appendix)
        return request.override(system_message=retry_system)

    def _prepare_request(self, request: ModelRequest) -> ModelRequest:
        patched = self._build_patched_messages(request.messages)
        if patched is None:
            return request
        return request.override(messages=patched)

    def _enforce_with_retry(
        self,
        request: ModelRequest,
        response: ModelResponse,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        if not self._needs_checkpoint_enforcement(request.messages):
            return response
        if self._response_calls_checkpoint(response):
            return response

        retry_request = request
        retry_response = response
        for appendix in CHECKPOINT_RETRY_APPENDICES:
            retry_request = self._build_retry_request(retry_request, appendix)
            retry_response = handler(retry_request)
            if self._response_calls_checkpoint(retry_response):
                return retry_response

        logger.warning(
            "KnowledgeCheckpointMiddleware could not force a checkpoint after %s substantive grounding results.",
            self._grounding_count_since_checkpoint(request.messages),
        )
        return retry_response

    async def _aenforce_with_retry(
        self,
        request: ModelRequest,
        response: ModelResponse,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        if not self._needs_checkpoint_enforcement(request.messages):
            return response
        if self._response_calls_checkpoint(response):
            return response

        retry_request = request
        retry_response = response
        for appendix in CHECKPOINT_RETRY_APPENDICES:
            retry_request = self._build_retry_request(retry_request, appendix)
            retry_response = await handler(retry_request)
            if self._response_calls_checkpoint(retry_response):
                return retry_response

        logger.warning(
            "KnowledgeCheckpointMiddleware could not force a checkpoint after %s substantive grounding results.",
            self._grounding_count_since_checkpoint(request.messages),
        )
        return retry_response

    def _build_blocked_tool_message(self, request: ToolCallRequest) -> ToolMessage:
        tool_name = request.tool_call.get("name", "unknown")
        count = self._grounding_count_since_checkpoint(self._extract_messages_from_state(request.state))
        return ToolMessage(
            content=(
                "Error: 已累计达到 knowledge_checkpoint 强制触发阈值。"
                f"当前自上次 checkpoint 以来已有 {count} 条有效的 `knowledge_search` / `knowledge_locate` 结果。"
                f"在调用 `{tool_name}` 之前，必须先调用 `knowledge_checkpoint` 总结已完成板块。"
            ),
            tool_call_id=request.tool_call.get("id", ""),
            name=tool_name,
            status="error",
        )

    def _should_block_tool_call(self, request: ToolCallRequest) -> bool:
        tool_name = request.tool_call.get("name")
        if tool_name == CHECKPOINT_TOOL_NAME:
            return False
        messages = self._extract_messages_from_state(request.state)
        if not messages:
            return False
        return self._needs_checkpoint_enforcement(messages)

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        prepared_request = self._prepare_request(request)
        response = handler(prepared_request)
        return self._enforce_with_retry(prepared_request, response, handler)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        prepared_request = self._prepare_request(request)
        response = await handler(prepared_request)
        return await self._aenforce_with_retry(prepared_request, response, handler)

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage],
    ) -> ToolMessage:
        if self._should_block_tool_call(request):
            return self._build_blocked_tool_message(request)
        return handler(request)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage]],
    ) -> ToolMessage:
        if self._should_block_tool_call(request):
            return self._build_blocked_tool_message(request)
        return await handler(request)
