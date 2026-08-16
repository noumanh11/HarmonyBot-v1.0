"""Prompt construction.

v1 flattened everything - context, examples and the question - into a single
``user`` string. That is why the model kept answering the *example* instead of
the user: it could not tell them apart. Here the persona goes in a ``system``
message and retrieved examples become real alternating user/assistant turns,
which is the shape instruction-tuned chat models are trained on.
"""

from __future__ import annotations

from app.schemas import Domain
from app.services.retrieval import Example

_SHARED_RULES = """
You are HarmonyBot, a supportive assistant.

Ground rules you must always follow:
- You are not a licensed clinician. Never present yourself as one.
- Do not give definitive diagnoses or specific prescription dosages.
- Encourage the user to consult a qualified professional for anything
  urgent, worsening, or serious.
- Answer the user's most recent question directly. Any earlier examples are
  reference material only - never respond to them as if they were the user.
- Be concise and warm. Use short paragraphs or bullet points.
- Format your reply in Markdown.
""".strip()

_DOMAIN_INSTRUCTIONS: dict[Domain, str] = {
    Domain.MEDICAL: (
        "The user has a health or medical question. Explain clearly in plain "
        "language, describe general possibilities rather than a firm "
        "diagnosis, and say plainly when something warrants seeing a doctor."
    ),
    Domain.MENTAL_HEALTH: (
        "The user is raising a mental-health or emotional concern. Lead with "
        "empathy, validate what they are feeling, and offer gentle, practical "
        "coping suggestions. Do not minimise their experience."
    ),
    Domain.GENERAL: (
        "The user has a general question outside the medical and mental-health "
        "domains. Answer helpfully and accurately."
    ),
}

_EXAMPLE_ROLE = {
    Domain.MEDICAL: "a patient and a doctor",
    Domain.MENTAL_HEALTH: "someone seeking support and a counsellor",
}


def build_messages(
    message: str,
    domain: Domain,
    examples: list[Example],
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Assemble the chat-completion message list."""
    system = f"{_SHARED_RULES}\n\n{_DOMAIN_INSTRUCTIONS[domain]}"

    if examples and domain in _EXAMPLE_ROLE:
        system += (
            f"\n\nBelow are reference exchanges between {_EXAMPLE_ROLE[domain]}, "
            "drawn from a dataset of past conversations. Use them only to guide "
            "your tone and depth. They are not part of this conversation."
        )
        for i, example in enumerate(examples, start=1):
            system += (
                f"\n\n--- Reference {i} ---\n"
                f"Question: {_truncate(example.question)}\n"
                f"Answer: {_truncate(example.answer)}"
            )

    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": message})
    return messages


def _truncate(text: str, limit: int = 600) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."
