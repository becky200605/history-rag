"""Stop a subagent that has burned through its tool-call budget.

When a subtask exceeds TOOL_CALL_LIMIT tool invocations without returning a
final answer, the middleware forces the model to stop calling tools and write
a structured text response in the same format as a normal task completion
(## 任务结果 / ## 关键发现 / ## 关键引文 / ## 未解决缺口), which the executor
then parses exactly like any other successful run.
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
    "【系统强制终止】本子任务已累计调用工具 {count} 次，超过上限（{limit} 次），执行时间过长，必须立即停止检索。\n\n"
    "请现在直接输出最终答案，不要再调用任何工具。按以下固定格式输出：\n\n"
    "## 任务结果\n"
    "- 直接说明当前已找到哪些内容，结论是什么\n"
    "- 同时如实说明为什么执行了这么久还没完成，给出具体原因，例如：\n"
    "    · 涉及书目太多、逐本检索耗时过长\n"
    "    · 检索关键词匹配率低、反复尝试仍无结果\n"
    "    · 问题范围太宽，单次子任务无法覆盖\n"
    "    · 书中确实缺乏相关记载\n"
    "    · 其他原因（请具体说明）\n\n"
    "## 关键发现\n"
    "- 已确认的关键事实，附 citation；没有则写「- 无充分证据支持结论」\n\n"
    "## 关键引文\n"
    "- 可复用的 citation 行；没有则写「- 无」\n\n"
    "## 未解决缺口\n"
    "- 还有哪些关键问题没有答案\n"
    "- 建议主任务如何跟进：①把范围拆细重新检索 ②换书目或检索方向 ③该问题在现有书库中可能无答案，建议放弃\n\n"
    "只输出上述四个 Markdown 节，不要调用任何工具。"
)

_HARD_STOP_MESSAGE = (
    "【再次警告】你仍在尝试调用工具，这是不允许的。\n"
    "必须立刻输出文本答案（## 任务结果 / ## 关键发现 / ## 关键引文 / ## 未解决缺口），不得再调用任何工具。"
)


class SubagentToolLimitMiddleware(AgentMiddleware[AgentState]):
    """Enforce a hard tool-call budget on subagents."""

    def _count_tool_calls(self, messages: list) -> int:
        """Count ToolMessage instances in the conversation history."""
        return sum(1 for m in messages if isinstance(m, ToolMessage))

    def _response_has_tool_calls(self, response: ModelResponse) -> bool:
        """Return True if the response contains any tool calls."""
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
            # Model already produced a text response — pass through.
            return response

        # Inject wrap-up instruction and hard-stop reminder together, then retry once.
        retry_request = self._build_hard_stop_request(
            self._build_wrap_up_request(request, tool_count)
        )
        retry_response = handler(retry_request)
        if not self._response_has_tool_calls(retry_response):
            return retry_response

        logger.warning(
            "SubagentToolLimitMiddleware: model still calling tools after hard stop "
            "(tool_count=%d). Returning last response.",
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
            "SubagentToolLimitMiddleware: model still calling tools after hard stop "
            "(tool_count=%d). Returning last response.",
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
