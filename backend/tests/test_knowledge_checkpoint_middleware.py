from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

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
