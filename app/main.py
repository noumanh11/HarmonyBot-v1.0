"""Application factory and lifespan wiring."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import __version__
from app.config import get_settings
from app.middleware import RateLimitMiddleware, SecurityHeadersMiddleware
from app.observability import RequestContextMiddleware, configure_logging
from app.routers import chat as chat_router
from app.routers import pages as pages_router
from app.services.chat import ChatService
from app.services.llm import LLMClient
from app.services.retrieval import KnowledgeBase
from app.services.sessions import SessionStore

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings

    knowledge_base = KnowledgeBase()
    app.state.knowledge_base = knowledge_base

    sessions = SessionStore(
        max_turns=settings.max_history_turns,
        ttl_seconds=settings.session_ttl_seconds,
        max_sessions=settings.max_sessions,
    )
    app.state.sessions = sessions

    llm = LLMClient(settings)
    app.state.llm = llm
    app.state.chat_service = ChatService(knowledge_base, llm, sessions, settings)

    # Indexing is CPU-bound and takes a few seconds; run it off the event loop
    # so startup does not block, and let a failure degrade rather than crash.
    await asyncio.to_thread(knowledge_base.load, settings)
    logger.info(
        "HarmonyBot %s ready (model=%s, retrieval=%s, docs=%d)",
        __version__,
        settings.model_id,
        knowledge_base.ready,
        knowledge_base.document_count,
        extra={
            "event": "startup",
            "version": __version__,
            "model": settings.model_id,
            "retrieval_ready": knowledge_base.ready,
            "documents": knowledge_base.document_count,
        },
    )

    yield

    await llm.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.json_logs)

    app = FastAPI(
        title="HarmonyBot",
        version=__version__,
        description="A medical and mental-health conversational assistant.",
        lifespan=lifespan,
    )

    # Middleware runs outermost-first, so the request id is established before
    # anything else can log, and rate limiting rejects before any work happens.
    app.add_middleware(RequestContextMiddleware)
    if settings.security_headers:
        app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        RateLimitMiddleware,
        limit=settings.rate_limit_requests,
        window=settings.rate_limit_window_seconds,
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

    app.mount(
        "/static",
        StaticFiles(directory=BASE_DIR / "static"),
        name="static",
    )
    app.state.templates = Jinja2Templates(directory=BASE_DIR / "templates")

    app.include_router(pages_router.router)
    app.include_router(chat_router.router)
    return app


app = create_app()
