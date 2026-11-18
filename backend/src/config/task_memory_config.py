"""Task-memory controls, independent of personal-profile memory."""

from pydantic import BaseModel, Field


class TaskMemoryConfig(BaseModel):
    enabled: bool = True
    retrieval_enabled: bool = True
    timeout_seconds: float = Field(default=3.0, gt=0, le=60)
    first_turn_timeout_seconds: float = Field(default=0.45, gt=0, le=60)
    cache_ttl_seconds: float = Field(default=60.0, ge=0, le=3600)
    cache_max_entries: int = Field(default=128, ge=1, le=4096)


_config = TaskMemoryConfig()


def get_task_memory_config() -> TaskMemoryConfig:
    return _config


def load_task_memory_config_from_dict(data: dict) -> None:
    global _config
    _config = TaskMemoryConfig(**data)
