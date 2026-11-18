"""Follow-up questions are optional and never hold the agent stream open."""

import asyncio
import logging
from types import SimpleNamespace

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.agents.middlewares.citation_enforcement_middleware import (
    CitationEnforcementMiddleware,
    _fallback_suggested_questions,
    _is_refusal,
)
from src.config.suggestions_config import get_suggestions_config
from src.models import create_chat_model

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/models", tags=["models"])
_slots = asyncio.Semaphore(4)


class SuggestionsRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    answer: str = Field(min_length=1, max_length=24000)


class SuggestionsResponse(BaseModel):
    questions: list[str]


@router.post("/suggestions", response_model=SuggestionsResponse)
async def generate_suggestions(body: SuggestionsRequest) -> SuggestionsResponse:
    config = get_suggestions_config()
    if config.mode != "deferred":
        return SuggestionsResponse(questions=[])
    fallback = _fallback_suggested_questions(user_question=body.question, refusal=_is_refusal(body.answer))
    try:
        # Include admission waiting in the deadline, and use a separate non-thinking model.
        async with asyncio.timeout(config.timeout_seconds):
            async with _slots:
                model = create_chat_model(name=config.model_name, thinking_enabled=False, max_tokens=256, timeout=config.timeout_seconds, max_retries=0)
                questions = await CitationEnforcementMiddleware()._generate_suggested_questions_async(
                    request=SimpleNamespace(model=model, messages=[]),
                    user_question=body.question,
                    answer_body=body.answer,
                    reference_section="",
                )
        return SuggestionsResponse(questions=questions)
    except Exception:
        logger.warning("Follow-up questions unavailable; using local fallback", exc_info=True)
        return SuggestionsResponse(questions=fallback)
