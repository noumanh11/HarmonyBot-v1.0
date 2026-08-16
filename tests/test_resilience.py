"""Failover, retries, rate limiting and security headers."""

import pytest

from app.config import Settings
from app.services.llm import LLMClient, LLMError, _is_permanent
from app.services.retrieval import _usable

# --- classification --------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "The requested model 'x' is not supported by any provider you have enabled.",
        "404 Client Error: Not Found",
        "403 Forbidden: model is gated",
    ],
)
def test_permanent_errors_detected(message):
    assert _is_permanent(Exception(message))


@pytest.mark.parametrize(
    "message",
    ["503 Service Unavailable", "Read timed out", "rate limit exceeded"],
)
def test_transient_errors_are_retryable(message):
    assert not _is_permanent(Exception(message))


# --- failover --------------------------------------------------------


class FakeStream:
    """Mimics the async iterator returned by chat_completion(stream=True)."""

    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        async def gen():
            for text in self._chunks:
                yield type(
                    "Chunk",
                    (),
                    {
                        "choices": [
                            type(
                                "Choice", (), {"delta": type("D", (), {"content": text})}
                            )
                        ]
                    },
                )
            # Terminating chunk with a null delta - v1 crashed here.
            yield type(
                "Chunk",
                (),
                {
                    "choices": [
                        type("Choice", (), {"delta": type("D", (), {"content": None})})
                    ]
                },
            )

        return gen()


class FakeHFClient:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = 0

    async def chat_completion(self, **_):
        self.calls += 1
        if isinstance(self.behaviour, Exception):
            raise self.behaviour
        return FakeStream(self.behaviour)

    async def close(self):
        pass


def build_client(behaviours: dict[str, object]) -> tuple[LLMClient, dict]:
    settings = Settings(
        hf_token="test",  # noqa: S106 - a stub token for a stub client
        model_id="primary",
        fallback_models=["secondary", "tertiary"],
        max_retries=1,
        retry_backoff=0.0,
    )
    client = LLMClient(settings)
    fakes = {name: FakeHFClient(b) for name, b in behaviours.items()}
    client._clients = fakes
    client._client = lambda model: fakes[model]
    return client, fakes


async def collect(client) -> str:
    return "".join([c async for c in client.stream([{"role": "user", "content": "hi"}])])


async def test_retired_primary_fails_over_to_next_model():
    """Exactly the v1 outage: the pinned model stops being served."""
    client, fakes = build_client(
        {
            "primary": Exception("model_not_supported"),
            "secondary": ["Hello ", "there"],
            "tertiary": ["unused"],
        }
    )

    assert await collect(client) == "Hello there"
    assert client.active_model == "secondary"
    assert fakes["tertiary"].calls == 0, "should stop at the first model that works"


async def test_failover_is_sticky():
    """After failing over, later requests skip the dead model entirely."""
    client, fakes = build_client(
        {
            "primary": Exception("model_not_supported"),
            "secondary": ["ok"],
            "tertiary": ["unused"],
        }
    )

    await collect(client)
    calls_after_first = fakes["primary"].calls
    await collect(client)
    assert fakes["primary"].calls == calls_after_first


async def test_permanent_error_is_not_retried():
    client, fakes = build_client(
        {
            "primary": Exception("model_not_supported"),
            "secondary": ["ok"],
            "tertiary": ["x"],
        }
    )
    await collect(client)
    assert fakes["primary"].calls == 1


async def test_transient_error_is_retried_on_the_same_model():
    client, fakes = build_client(
        {
            "primary": Exception("503 Service Unavailable"),
            "secondary": ["ok"],
            "tertiary": ["x"],
        }
    )
    await collect(client)
    assert fakes["primary"].calls == 2, "one attempt plus one retry"


async def test_all_models_failing_raises_llm_error():
    client, _ = build_client(
        {
            "primary": Exception("model_not_supported"),
            "secondary": Exception("model_not_supported"),
            "tertiary": Exception("model_not_supported"),
        }
    )
    with pytest.raises(LLMError):
        await collect(client)


async def test_null_delta_chunk_is_skipped():
    client, _ = build_client(
        {
            "primary": ["a", "b"],
            "secondary": [],
            "tertiary": [],
        }
    )
    assert await collect(client) == "ab"


# --- corpus filtering ------------------------------------------------


def test_boilerplate_rows_are_dropped():
    """These generic rows outranked real matches for every question."""
    answer = "A" * 60
    assert not _usable("Hi, may I answer your health queries right now ?", answer)
    assert not _usable("Welcome to Chat Doctor, please type your query.", answer)
    assert not _usable("hello", answer)


def test_short_rows_are_dropped():
    assert not _usable("I have a fever", "A" * 60)
    assert not _usable("A" * 60, "ok")


def test_real_exchanges_are_kept():
    assert _usable(
        "I have had a persistent cough and fever for five days now.",
        "That sounds like it could be a viral infection. Please see a doctor.",
    )


# --- middleware ------------------------------------------------------


def test_security_headers_present(client):
    res = client.get("/")
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in res.headers["Content-Security-Policy"]


def test_request_id_echoed(client):
    res = client.get("/health")
    assert res.headers.get("X-Request-ID")


def test_upstream_request_id_is_honoured(client):
    res = client.get("/health", headers={"X-Request-ID": "trace-me-123"})
    assert res.headers["X-Request-ID"] == "trace-me-123"


def test_rate_limit_returns_429(client):
    codes = [client.post("/chat", json={"message": "hi"}).status_code for _ in range(25)]
    assert 429 in codes, "generation endpoint should be rate limited"
    assert codes.index(429) >= 20, "limit should not trip too early"


def test_rate_limit_does_not_apply_to_health(client):
    codes = [client.get("/health").status_code for _ in range(30)]
    assert set(codes) == {200}
