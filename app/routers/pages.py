"""HTML and health endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app import __version__
from app.schemas import HealthResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index(request: Request) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(
        request=request, name="index.html", context={}
    )


@router.get("/health", response_model=HealthResponse, tags=["ops"])
async def health(request: Request) -> HealthResponse:
    """Liveness + readiness, so a container orchestrator can probe the app."""
    kb = request.app.state.knowledge_base
    llm = request.app.state.llm
    return HealthResponse(
        status="ok",
        version=__version__,
        # The *active* model, which may be a fallback if the primary was
        # retired - reporting the configured id would hide that.
        model=getattr(llm, "active_model", request.app.state.settings.model_id),
        retrieval_ready=kb.ready,
        indexed_documents=kb.document_count,
    )
