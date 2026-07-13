from typing import Any

from pydantic import BaseModel


class SSEMessage(BaseModel):
    """SSE 事件统一结构，前端按 event 字段分发处理。"""

    event: str
    run_id: str
    phase: str | None = None
    message: str
    data: dict[str, Any] = {}
