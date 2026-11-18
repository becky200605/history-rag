"""Optional follow-up questions, generated after the answer completes."""

from typing import Literal

from pydantic import BaseModel, Field


class SuggestionsConfig(BaseModel):
    mode: Literal["inline", "deferred", "disabled"] = "deferred"
    model_name: str | None = None
    timeout_seconds: float = Field(default=10.0, gt=0, le=60)


_config = SuggestionsConfig()


def get_suggestions_config() -> SuggestionsConfig:
    return _config


def set_suggestions_config(config: SuggestionsConfig) -> None:
    global _config
    _config = config


def load_suggestions_config_from_dict(data: dict) -> None:
    set_suggestions_config(SuggestionsConfig(**data))
