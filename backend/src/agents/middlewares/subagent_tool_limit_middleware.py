"""Stop a subagent that has burned through its tool-call budget.

When a subtask exceeds TOOL_CALL_LIMIT tool invocations without returning a
final answer, the middleware injects a system message that forces the model to
wrap up: explain what it found (or didn't), diagnose why retrieval stalled, and
recommend whether the lead agent should retry with a narrower scope or abandon
the direction.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

logger = logging.getLogger(__name__)

TOOL_CALL_LIMIT = 20

_WRAP_UP_MESSAGE = (
    "【系统限制】本子任务已累计调用工具 {count} 次，已达到上限（{limit} 次）。\n"
    "请立刻停止检索，不要再调用任何工具，直接按以下格式返回当前状态：\n\n"
    "## 任务结果\n"
    "说明当前已找到的内容（如有），以及为什么检索这么久仍未得到充分证据。\n\n"
    "## 关键发现\n"
    "- 列出已确认的事实（如有），附 citation；如果什么都没找到，写「- 无」\n\n"
    "## 关键引文\n"
    "- 列出可复用的 citation（如有）；没有则写「- 无」\n\n"
    "## 未解决缺口\n"
    "- 详细说明：检索方向是否有误？书籍选择是否合适？\n"
    "- 主任务应该如何跟进：①把任务拆得更细再试，②换其他书目方向，还是③放弃这个检索方向？\n"
    "请给出明确建议。"
)

_HARD_STOP_MESSAGE = (
    "【系统再次提醒】你仍在尝试调用工具。现在必须停止，只输出文字回复，格式如上。"
)


class SubagentToolLimitMiddleware(AgentMiddleware[AgentState]):
    """Enforce a hard tool-call budget on subagents."""

    def _count_tool_calls(self, messages: list) -> int:
        """Count ToolMessage instances in the conversation history."""
        return sum(1 for m in messages if isinstance(m, ToolMessage))

    def _response_has_tool_calls(self, response: ModelResponse) -> bool:
        for message in response.result:
            if isinstance(message, AIMessage) and message.tool_calls:
                return True
        return False

    def _build_wrap_up_request(self, request: ModelRequest, count: int) -> ModelRequest:
        reminder = HumanMessage(
            content=_WRAP_UP_MESSAGE.format(count=count, limit=TOOL_CALL_LIMIT)
        )
        return request.override(messages=[*request.messages, reminder])

    def _build_hard_stop_request(self, request: ModelRequest) -> ModelRequest:
        reminder = HumanMessage(content=_HARD_STOP_MESSAGE)
        return request.override(messages=[*request.messages, reminder])

    def _enforce(
        self,
        request: ModelRequest,
        response: ModelResponse,
        handler: Callable[[ModelRequest], ModelResponse],
        *,
        tool_count: int,
    ) -> ModelResponse:
        if not self._response_has_tool_calls(response):
            return response

        # Inject both the wrap-up instruction and the hard-stop reminder, then retry once
        retry_request = self._build_hard_stop_request(
            self._build_wrap_up_request(request, tool_count)
        )
        retry_response = handler(retry_request)
        if not self._response_has_tool_calls(retry_response):
            return retry_response

        logger.warning(
            "SubagentToolLimitMiddleware: model still calling tools after hard stop (tool_count=%d). "
            "Returning last response.",
            tool_count,
        )
        return retry_response

    async def _aenforce(
        self,
        request: ModelRequest,
        response: ModelResponse,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
        *,
        tool_count: int,
    ) -> ModelResponse:
        if not self._response_has_tool_calls(response):
            return response

        retry_request = self._build_hard_stop_request(
            self._build_wrap_up_request(request, tool_count)
        )
        retry_response = await handler(retry_request)
        if not self._response_has_tool_calls(retry_response):
            return retry_response

        logger.warning(
            "SubagentToolLimitMiddleware: model still calling tools after hard stop (tool_count=%d). "
            "Returning last response.",
            tool_count,
        )
        return retry_response

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        response = handler(request)
        tool_count = self._count_tool_calls(request.messages)
        if tool_count < TOOL_CALL_LIMIT:
            return response
        logger.info(
            "SubagentToolLimitMiddleware: tool call limit reached (count=%d, limit=%d), forcing wrap-up.",
            tool_count,
            TOOL_CALL_LIMIT,
        )
        return self._enforce(request, response, handler, tool_count=tool_count)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        response = await handler(request)
        tool_count = self._count_tool_calls(request.messages)
        if tool_count < TOOL_CALL_LIMIT:
            return response
        logger.info(
            "SubagentToolLimitMiddleware: tool call limit reached (count=%d, limit=%d), forcing wrap-up.",
            tool_count,
            TOOL_CALL_LIMIT,
        )
        return await self._aenforce(request, response, handler, tool_count=tool_count)
