from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from src.agents.middlewares.knowledge_checkpoint_middleware import (
    KnowledgeCheckpointMiddleware,
)


def _build_request(messages: list) -> ModelRequest:
    return ModelRequest(
        model=object(),
        messages=messages,
        system_message=SystemMessage(content="You are a helpful assistant."),
    )


def _response() -> ModelResponse:
    return ModelResponse(result=[AIMessage(content="ok")])


def _tool_call_response(name: str) -> ModelResponse:
    return ModelResponse(
        result=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": f"{name}-call-1",
                        "name": name,
                        "args": {
                            "title": "北洋政府财政",
                            "summary": "已整理本板块发现",
                            "citations": ["citation: ..."],
                        },
                        "type": "tool_call",
                    }
                ],
            )
        ]
    )


def _tool_request(name: str, messages: list) -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"id": f"{name}-tool-call", "name": name, "args": {}, "type": "tool_call"},
        tool=None,
        state={"messages": messages},
        runtime=None,
    )


def test_replaces_grounding_payloads_before_latest_checkpoint_only():
    middleware = KnowledgeCheckpointMiddleware()
    seen_messages: list = []
    request = _build_request(
        [
            HumanMessage(content="请继续总结"),
            ToolMessage(content="very long search result", tool_call_id="ks-1", name="knowledge_search"),
            ToolMessage(content="very long locate result", tool_call_id="kl-1", name="knowledge_locate"),
            ToolMessage(content="checkpoint A", tool_call_id="cp-1", name="knowledge_checkpoint"),
            ToolMessage(content="new search result", tool_call_id="ks-2", name="knowledge_search"),
        ]
    )

    def handler(current_request: ModelRequest) -> ModelResponse:
        seen_messages.extend(current_request.messages)
        return _response()

    middleware.wrap_model_call(request, handler)

    assert str(seen_messages[1].content).startswith("【已调用knowledge_search工具】")
    assert str(seen_messages[2].content).startswith("【已调用knowledge_locate工具】")
    assert str(seen_messages[3].content) == "checkpoint A"
    assert str(seen_messages[4].content) == "new search result"


def test_leaves_messages_untouched_when_no_checkpoint_exists():
    middleware = KnowledgeCheckpointMiddleware()
    seen_messages: list = []
    request = _build_request(
        [
            HumanMessage(content="请继续总结"),
            ToolMessage(content="raw search result", tool_call_id="ks-1", name="knowledge_search"),
        ]
    )

    def handler(current_request: ModelRequest) -> ModelResponse:
        seen_messages.extend(current_request.messages)
        return _response()

    middleware.wrap_model_call(request, handler)

    assert str(seen_messages[1].content) == "raw search result"


def test_retries_until_model_calls_checkpoint_after_grounding_threshold():
    middleware = KnowledgeCheckpointMiddleware()
    request = _build_request(
        [
            HumanMessage(content="请继续整理表格"),
            ToolMessage(content="substantive search result 1", tool_call_id="ks-1", name="knowledge_search"),
            ToolMessage(content="substantive locate result 2", tool_call_id="kl-1", name="knowledge_locate"),
            ToolMessage(content="substantive search result 3", tool_call_id="ks-2", name="knowledge_search"),
            ToolMessage(content="substantive locate result 4", tool_call_id="kl-2", name="knowledge_locate"),
            ToolMessage(content="substantive search result 5", tool_call_id="ks-3", name="knowledge_search"),
        ]
    )
    seen_requests: list[ModelRequest] = []
    responses = [
        _tool_call_response("knowledge_search"),
        _tool_call_response("knowledge_checkpoint"),
    ]

    def handler(current_request: ModelRequest) -> ModelResponse:
        seen_requests.append(current_request)
        return responses[len(seen_requests) - 1]

    final_response = middleware.wrap_model_call(request, handler)

    assert len(seen_requests) == 2
    assert "NEXT action must be exactly one call to `knowledge_checkpoint`" in str(
        seen_requests[1].system_message.content
    )
    final_ai = final_response.result[-1]
    assert isinstance(final_ai, AIMessage)
    assert final_ai.tool_calls[0]["name"] == "knowledge_checkpoint"


def test_does_not_enforce_checkpoint_for_non_substantive_grounding_results():
    middleware = KnowledgeCheckpointMiddleware()
    request = _build_request(
        [
            HumanMessage(content="请继续整理表格"),
            ToolMessage(
                content="本轮没有命中到可直接使用的内部知识片段。",
                tool_call_id="ks-1",
                name="knowledge_search",
            ),
            ToolMessage(
                content="No matching page/paragraph/line context found.",
                tool_call_id="kl-1",
                name="knowledge_locate",
            ),
        ]
    )
    seen_requests: list[ModelRequest] = []

    def handler(current_request: ModelRequest) -> ModelResponse:
        seen_requests.append(current_request)
        return _response()

    middleware.wrap_model_call(request, handler)

    assert len(seen_requests) == 1


def test_blocks_non_checkpoint_tool_call_after_threshold():
    middleware = KnowledgeCheckpointMiddleware()
    request = _tool_request(
        "knowledge_locate",
        [
            HumanMessage(content="请继续整理表格"),
            ToolMessage(content="substantive search result 1", tool_call_id="ks-1", name="knowledge_search"),
            ToolMessage(content="substantive locate result 2", tool_call_id="kl-1", name="knowledge_locate"),
            ToolMessage(content="substantive search result 3", tool_call_id="ks-2", name="knowledge_search"),
            ToolMessage(content="substantive locate result 4", tool_call_id="kl-2", name="knowledge_locate"),
            ToolMessage(content="substantive search result 5", tool_call_id="ks-3", name="knowledge_search"),
        ],
    )

    def handler(_: ToolCallRequest) -> ToolMessage:
        return ToolMessage(content="should not execute", tool_call_id="knowledge_locate-tool-call")

    result = middleware.wrap_tool_call(request, handler)

    assert result.status == "error"
    assert "必须先调用 `knowledge_checkpoint`" in str(result.content)
    assert result.name == "knowledge_locate"


def test_allows_checkpoint_tool_call_after_threshold():
    middleware = KnowledgeCheckpointMiddleware()
    request = _tool_request(
        "knowledge_checkpoint",
        [
            HumanMessage(content="请继续整理表格"),
            ToolMessage(content="substantive search result 1", tool_call_id="ks-1", name="knowledge_search"),
            ToolMessage(content="substantive locate result 2", tool_call_id="kl-1", name="knowledge_locate"),
            ToolMessage(content="substantive search result 3", tool_call_id="ks-2", name="knowledge_search"),
            ToolMessage(content="substantive locate result 4", tool_call_id="kl-2", name="knowledge_locate"),
            ToolMessage(content="substantive search result 5", tool_call_id="ks-3", name="knowledge_search"),
        ],
    )

    def handler(_: ToolCallRequest) -> ToolMessage:
        return ToolMessage(content="checkpoint executed", tool_call_id="knowledge_checkpoint-tool-call")

    result = middleware.wrap_tool_call(request, handler)

    assert result.status == "success"
    assert str(result.content) == "checkpoint executed"
