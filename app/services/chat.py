"""Chat orchestration: route -> retrieve -> prompt -> generate -> render.

Keeping this in one service (rather than in the route handler, as v1 did)
means the streaming and non-streaming endpoints share exactly one pipeline.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.prompts import build_messages
from app.schemas import Domain
from app.services.llm import LLMClient
from app.services.rendering import render_markdown
from app.services.retrieval import KnowledgeBase
from app.services.safety import CRISIS_NOTICE, is_crisis
from app.services.sessions import SessionStore


@dataclass
class Turn:
    """Everything the pipeline decided before generation starts."""

    domain: Domain
    crisis: bool
    messages: list[dict[str, str]]


class ChatService:
    def __init__(
        self,
        knowledge_base: KnowledgeBase,
        llm: LLMClient,
        sessions: SessionStore,
        settings,
    ) -> None:
        self._kb = knowledge_base
        self._llm = llm
        self._sessions = sessions
        self._settings = settings

    def prepare(
        self,
        message: str,
        session_id: str,
        history: list[dict[str, str]] | None = None,
    ) -> Turn:
        domain = self._kb.route(message)
        examples = self._kb.retrieve(message, domain, self._settings)
        # A client-supplied history is authoritative; it survives restarts and
        # lets the caller edit or regenerate a turn cleanly.
        if history is None:
            history = self._sessions.history(session_id)
        return Turn(
            domain=domain,
            crisis=is_crisis(message),
            messages=build_messages(message, domain, examples, history),
        )

    async def respond(
        self,
        message: str,
        session_id: str,
        history: list[dict[str, str]] | None = None,
    ) -> tuple[str, Turn]:
        """Generate a full reply and return it as sanitised HTML."""
        turn = self.prepare(message, session_id, history)
        text = await self._llm.complete(turn.messages)
        if history is None:
            self._record(session_id, message, text)
        return render_markdown(self._decorate(text, turn)), turn

    async def stream(
        self,
        message: str,
        session_id: str,
        history: list[dict[str, str]] | None = None,
    ) -> AsyncIterator[tuple[str, str]]:
        """Yield ``(event, payload)`` pairs for server-sent events.

        Text is streamed raw so the browser can show it as it arrives, then a
        final ``done`` event carries the sanitised HTML that replaces it. The
        browser never renders un-sanitised model output as markup.
        """
        turn = self.prepare(message, session_id, history)
        yield "meta", turn.domain.value

        if turn.crisis:
            yield "crisis", render_markdown(CRISIS_NOTICE)

        parts: list[str] = []
        async for delta in self._llm.stream(turn.messages):
            parts.append(delta)
            yield "delta", delta

        text = "".join(parts)
        if history is None:
            self._record(session_id, message, text)
        yield "done", render_markdown(text)

    def _decorate(self, text: str, turn: Turn) -> str:
        if turn.crisis:
            return f"{CRISIS_NOTICE}\n\n{text}"
        return text

    def _record(self, session_id: str, user_message: str, reply: str) -> None:
        self._sessions.append(session_id, "user", user_message)
        if reply.strip():
            self._sessions.append(session_id, "assistant", reply)
