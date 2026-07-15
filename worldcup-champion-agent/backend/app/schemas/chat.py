"""Chat API schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ChatSessionCreate(BaseModel):
    """Create a chat session."""


class ChatMessageRequest(BaseModel):
    """User chat input."""

    message: str = Field(min_length=1, max_length=4000)
    force_web_search: bool = False


class StartPredictionRequest(BaseModel):
    """Start a prediction from the chat panel."""

    monte_carlo_runs: int = Field(default=1000, ge=100, le=10000)


class ChatMessageOut(BaseModel):
    """Message payload emitted over chat SSE."""

    role: Literal["user", "agent", "system"]
    content: str
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    phase: str | None = None
    data: dict | None = None
