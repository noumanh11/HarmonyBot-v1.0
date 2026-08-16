"""Retrieval, prompting, safety and rendering."""

import pytest

from app.prompts import build_messages
from app.schemas import Domain
from app.services.rendering import render_markdown
from app.services.retrieval import Example, KnowledgeBase, _Index
from app.services.safety import is_crisis
from app.services.sessions import SessionStore

# --- routing ---------------------------------------------------------


@pytest.mark.parametrize(
    "message,expected",
    [
        ("What are the symptoms of the flu?", Domain.MEDICAL),
        ("I have been feeling anxious and depressed", Domain.MENTAL_HEALTH),
        ("What is the capital of France?", Domain.GENERAL),
    ],
)
def test_routing(message, expected):
    assert KnowledgeBase().route(message) == expected


def test_routing_counts_hits_rather_than_first_match():
    """v1 returned the first list that matched; ties should go to weight."""
    kb = KnowledgeBase()
    assert kb.route("anxiety therapy counseling about my surgery") == Domain.MENTAL_HEALTH


# --- retrieval -------------------------------------------------------


def test_index_returns_the_nearest_question_not_the_first_row():
    questions = [
        "My son had an appendectomy and has blood in his stool",
        "What are the symptoms of influenza and fever?",
        "How do I treat a sprained ankle?",
    ]
    answers = ["appendectomy answer", "flu answer", "ankle answer"]
    index = _Index(questions, answers)

    hits = index.search("what are the symptoms of the flu", top_k=1, min_score=0.0)
    assert hits and hits[0].answer == "flu answer"


def test_index_drops_results_below_the_similarity_floor():
    index = _Index(
        ["my son had an appendectomy", "treating a sprained ankle"],
        ["a", "b"],
    )
    assert index.search("quantum chromodynamics", top_k=2, min_score=0.5) == []


# --- prompting -------------------------------------------------------


def test_examples_are_attributed_correctly():
    """v1 labelled the patient's message 'Doctor:' and the reply 'Patient:'."""
    example = Example(question="I have a fever", answer="Take paracetamol", score=0.9)
    messages = build_messages("I have a fever", Domain.MEDICAL, [example])

    system = messages[0]["content"]
    assert messages[0]["role"] == "system"
    assert "Question: I have a fever" in system
    assert "Answer: Take paracetamol" in system


def test_user_question_is_its_own_message():
    """The whole point: the model must be able to tell question from example."""
    example = Example(question="unrelated", answer="unrelated", score=0.9)
    messages = build_messages("my actual question", Domain.MEDICAL, [example])

    assert messages[-1] == {"role": "user", "content": "my actual question"}
    assert "reference" in messages[0]["content"].lower()


def test_history_sits_between_system_and_question():
    history = [
        {"role": "user", "content": "earlier"},
        {"role": "assistant", "content": "reply"},
    ]
    messages = build_messages("now", Domain.GENERAL, [], history)
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]


# --- safety ----------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    ["I want to kill myself", "thinking about suicide", "I want to die"],
)
def test_crisis_detected(message):
    assert is_crisis(message)


@pytest.mark.parametrize(
    "message",
    ["I have a headache", "my plant died", "this deadline is killing me"],
)
def test_no_false_crisis(message):
    assert not is_crisis(message)


# --- rendering -------------------------------------------------------


def test_script_tags_are_neutralised():
    """v1 piped raw model output into innerHTML."""
    html = render_markdown("Hello <script>alert('xss')</script>")
    assert "<script>" not in html
    assert "alert" not in html or "&lt;script&gt;" in html


def test_event_handlers_cannot_execute():
    html = render_markdown('<img src=x onerror="alert(1)">')
    # The tag is escaped to text, so no element exists to fire the handler.
    assert "<img" not in html
    assert "&lt;img" in html


def test_markdown_still_renders():
    html = render_markdown("**bold** and `code`\n\n- one\n- two")
    assert "<strong>bold</strong>" in html
    assert "<code>code</code>" in html
    assert "<li>one</li>" in html


def test_links_get_safe_rel():
    html = render_markdown("[x](https://example.com)")
    assert 'rel="noopener noreferrer nofollow"' in html


# --- sessions --------------------------------------------------------


def test_history_window_is_bounded():
    store = SessionStore(max_turns=2, ttl_seconds=3600, max_sessions=10)
    for i in range(10):
        store.append("s1", "user", f"m{i}")
    assert len(store.history("s1")) == 4  # 2 turns x 2 messages


def test_sessions_are_isolated():
    store = SessionStore(max_turns=4, ttl_seconds=3600, max_sessions=10)
    store.append("a", "user", "secret")
    assert store.history("b") == []


def test_lru_eviction_caps_memory():
    store = SessionStore(max_turns=2, ttl_seconds=3600, max_sessions=3)
    for i in range(5):
        store.append(f"s{i}", "user", "hi")
    assert store.history("s0") == []  # evicted
    assert store.history("s4") != []
