from langchain_core.messages import AIMessageChunk

from src.models.patched_openai_reasoning import PatchedChatOpenAIReasoning


def _build_model() -> PatchedChatOpenAIReasoning:
    return PatchedChatOpenAIReasoning(
        model="mlx-community/Qwen3.5-27B-4bit",
        api_key="dummy",
        base_url="https://model.kbkbk.xyz/v1",
    )


def test_create_chat_result_maps_reasoning_into_reasoning_content() -> None:
    model = _build_model()
    result = model._create_chat_result(
        {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": "mlx-community/Qwen3.5-27B-4bit",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "2+2 等于 4。",
                        "reasoning": "先做加法，然后直接回答。",
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 12,
                "total_tokens": 22,
            },
        }
    )

    message = result.generations[0].message
    assert message.content == "2+2 等于 4。"
    assert message.additional_kwargs["reasoning_content"] == "先做加法，然后直接回答。"


def test_stream_chunk_maps_delta_reasoning_into_reasoning_content() -> None:
    model = _build_model()
    chunk = model._convert_chunk_to_generation_chunk(
        {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "model": "mlx-community/Qwen3.5-27B-4bit",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": None,
                    "delta": {
                        "role": "assistant",
                        "reasoning": "Thinking",
                    },
                }
            ],
        },
        default_chunk_class=AIMessageChunk,
        base_generation_info=None,
    )

    assert chunk is not None
    assert chunk.message.additional_kwargs["reasoning_content"] == "Thinking"
