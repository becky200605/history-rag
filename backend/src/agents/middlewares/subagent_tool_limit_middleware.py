"""Stop a subagent that has burned through its tool-call budget.

When a subtask exceeds TOOL_CALL_LIMIT tool invocations without returning a
final answer, the middleware strips all tools from the next model call so the
model physically cannot invoke any more tools and must write a structured text
response in the same format as a normal task completion
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
from langchain_core.messages import HumanMessage, ToolMessage

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


class SubagentToolLimitMiddleware(AgentMiddleware[AgentState]):
    """Enforce a hard tool-call budget on subagents.

    Once the conversation contains TOOL_CALL_LIMIT ToolMessages, the next
    model call is rewritten so that:
      1. A wrap-up instruction is appended to the message history.
      2. The tool list is set to [] — the model has no tools available and
         MUST produce a plain-text response.

    This is a hard enforcement: no retry loop is needed because the model
    physically cannot call any tools when ``tools=[]``.
    """

    def _count_tool_calls(self, messages: list) -> int:
        """Count ToolMessage instances in the conversation history."""
        return sum(1 for m in messages if isinstance(m, ToolMessage))

    def _build_stripped_request(self, request: ModelRequest, tool_count: int) -> ModelRequest:
        """Inject wrap-up instruction and strip all tools from the request."""
        reminder = HumanMessage(
            content=_WRAP_UP_MESSAGE.format(count=tool_count, limit=TOOL_CALL_LIMIT)
        )
        return request.override(messages=[*request.messages, reminder], tools=[])

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        tool_count = self._count_tool_calls(request.messages)
        if tool_count < TOOL_CALL_LIMIT:
            return handler(request)
        logger.info(
            "SubagentToolLimitMiddleware: tool call limit reached (count=%d, limit=%d), stripping tools.",
            tool_count,
            TOOL_CALL_LIMIT,
        )
        return handler(self._build_stripped_request(request, tool_count))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        tool_count = self._count_tool_calls(request.messages)
        if tool_count < TOOL_CALL_LIMIT:
            return await handler(request)
        logger.info(
            "SubagentToolLimitMiddleware: tool call limit reached (count=%d, limit=%d), stripping tools.",
            tool_count,
            TOOL_CALL_LIMIT,
        )
        return await handler(self._build_stripped_request(request, tool_count))
