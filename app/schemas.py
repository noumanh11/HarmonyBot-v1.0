"""Request and response models.

Validation lives here so malformed input fails as a 422 at the edge instead
of a 500 from a KeyError deep in the handler.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Domain(StrEnum):
    """Which knowledge base a question was routed to."""

    MEDICAL = "medical"
    MENTAL_HEALTH = "mental_health"
    GENERAL = "general"


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str | None = Field(
        default=None,
        max_length=64,
        description="Opaque client-generated id used to thread conversation history.",
    )
    history: list[Message] | None = Field(
        default=None,
        max_length=20,
        description=(
            "Prior turns supplied by the client. When present these win over "
            "the server's in-memory session, so a conversation restored from "
            "the browser keeps its context across a server restart - and the "
            "server stays effectively stateless."
        ),
    )


class ResetRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=64)


class ChatResponse(BaseModel):
    response: str = Field(..., description="Sanitised HTML, safe to inject.")
    domain: Domain
    session_id: str
    crisis: bool = Field(
        default=False,
        description="True when the message tripped crisis detection and "
        "helpline resources were prepended.",
    )


class HealthResponse(BaseModel):
    status: str
    version: str
    model: str
    retrieval_ready: bool
    indexed_documents: int
