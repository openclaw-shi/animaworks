from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field


class CronTask(BaseModel):
    name: str
    schedule: str
    description: str


class ModelConfig(BaseModel):
    """Per-person API key, model, and endpoint configuration."""

    model: str = "claude-sonnet-4-20250514"
    fallback_model: str | None = None
    max_tokens: int = 4096
    max_turns: int = 20
    api_key_env: str = "ANTHROPIC_API_KEY"
    api_base_url: str | None = None  # e.g. http://localhost:11434/v1
    context_threshold: float = 0.50  # short-term memory externalization threshold
    max_chains: int = 2  # max auto-continuation sessions


class PersonConfig(BaseModel):
    name: str
    base_dir: Path
    identity: str = ""
    injection: str = ""
    permissions: str = ""
    heartbeat_interval: int = 30  # minutes
    active_hours: tuple[int, int] = (9, 22)
    cron_tasks: list[CronTask] = []
    model_config_data: ModelConfig = Field(default_factory=ModelConfig)


class Message(BaseModel):
    id: str = Field(
        default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    )
    thread_id: str = ""  # conversation thread (empty = new thread)
    reply_to: str = ""  # id of message being replied to
    from_person: str
    to_person: str
    type: str = "message"
    content: str
    attachments: list[str] = []
    timestamp: datetime = Field(default_factory=datetime.now)


class CycleResult(BaseModel):
    trigger: str
    action: str
    summary: str = ""
    duration_ms: int = 0
    timestamp: datetime = Field(default_factory=datetime.now)
    context_usage_ratio: float = 0.0
    session_chained: bool = False
    total_turns: int = 0


class PersonStatus(BaseModel):
    name: str
    status: str = "idle"
    current_task: str = ""
    last_heartbeat: datetime | None = None
    last_activity: datetime | None = None
    pending_messages: int = 0
