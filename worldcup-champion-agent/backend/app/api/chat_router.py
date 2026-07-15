"""Chat API routes."""

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from app.schemas.chat import ChatMessageRequest, ChatSessionCreate, StartPredictionRequest
from app.services.chat_service import (
    create_session,
    get_session,
    send_message,
    start_prediction_from_chat,
    stream_session,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/sessions")
async def new_session(_: ChatSessionCreate | None = None) -> dict[str, str]:
    session = create_session()
    return {"session_id": session.session_id}


@router.post("/sessions/{session_id}/messages")
async def chat_message(session_id: str, payload: ChatMessageRequest) -> dict[str, str]:
    if not get_session(session_id):
        raise HTTPException(status_code=404, detail="Chat session does not exist")
    await send_message(session_id, payload.message, force_web_search=payload.force_web_search)
    return {"status": "ok"}


@router.post("/sessions/{session_id}/predict")
async def start_predict(session_id: str, payload: StartPredictionRequest) -> dict[str, str]:
    if not get_session(session_id):
        raise HTTPException(status_code=404, detail="Chat session does not exist")
    run_id = await start_prediction_from_chat(session_id, payload.monte_carlo_runs)
    return {"run_id": run_id, "status": "started"}


@router.get("/sessions/{session_id}/stream")
async def chat_stream(session_id: str) -> EventSourceResponse:
    if not get_session(session_id):
        raise HTTPException(status_code=404, detail="Chat session does not exist")
    return EventSourceResponse(stream_session(session_id))
