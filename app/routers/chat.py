"""Chat endpoints."""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from app.schemas import ChatRequest, ChatResponse, ResetRequest
from app.services.chat import ChatService
from app.services.llm import LLMError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


def _service(request: Request) -> ChatService:
    return request.app.state.chat_service


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """Generate a complete reply. Kept for clients that cannot stream."""
    session_id = payload.session_id or uuid.uuid4().hex
    try:
        html, turn = await _service(request).respond(
            payload.message, session_id, _history(payload)
        )
    except LLMError as exc:
        # 502, not 500: the failure is upstream, and the detail is a generic
        # message rather than v1's raw exception string.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The language model is unavailable. Please try again.",
        ) from exc

    return ChatResponse(
        response=html,
        domain=turn.domain,
        session_id=session_id,
        crisis=turn.crisis,
    )


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    """Stream the reply as server-sent events."""
    session_id = payload.session_id or uuid.uuid4().hex
    service = _service(request)

    history = _history(payload)

    async def event_source():
        yield _sse("session", session_id)
        try:
            async for event, data in service.stream(payload.message, session_id, history):
                yield _sse(event, data)
        except LLMError:
            yield _sse("error", "The language model is unavailable. Please try again.")
        except Exception:
            logger.exception("Unexpected failure while streaming")
            yield _sse("error", "Something went wrong. Please try again.")

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # stop nginx buffering the stream
        },
    )


@router.post(
    "/chat/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def reset(payload: ResetRequest, request: Request) -> Response:
    """Drop a session's history. Replaces v1's dead /shutdown endpoint."""
    if payload.session_id:
        request.app.state.sessions.clear(payload.session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _history(payload: ChatRequest) -> list[dict[str, str]] | None:
    """Normalise client-supplied history, or None to fall back to the session."""
    if payload.history is None:
        return None
    return [{"role": m.role, "content": m.content} for m in payload.history]


def _sse(event: str, data: str) -> str:
    """Encode one SSE frame. JSON-encoding keeps newlines from breaking framing."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
