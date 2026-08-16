"""Dataset-backed example retrieval.

v1 shipped two bugs that compounded into nonsense answers:

  1. It always injected ``train[0]`` regardless of what the user asked, so
     every medical question was answered against the same appendectomy case.
  2. It swapped the roles. In ``avaliev/chat_doctor`` the ``input`` column is
     the *patient's* message and ``output`` is the *doctor's* reply, but the
     prompt labelled them "Doctor:" and "Patient:" respectively.

This module replaces that with TF-IDF nearest-neighbour lookup over the
patient/user side of each corpus, returning correctly-attributed Q/A pairs
that are actually related to the question.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.schemas import Domain

logger = logging.getLogger(__name__)

# Both corpora contain filler turns - greetings, "please type your query",
# transcription placeholders. They share vocabulary with everything and so
# score well against any question while teaching the model nothing. Left in,
# the top medical hit for "symptoms of the flu" is literally
# "Hi, may I answer your health queries right now?".
_BOILERPLATE = re.compile(
    r"may i answer your health quer|please type your query|"
    r"welcome to chat ?doctor|thanks? for (your )?(query|question) (to|at) chat ?doctor|"
    r"^\s*(hi|hello|hey|thanks?|thank you|ok|okay)[\s.!,]*$|"
    r"^\s*(hcm|chat ?doctor)[\s.]*$",
    re.IGNORECASE,
)

_MIN_CHARS = 40


def _usable(question: str, answer: str) -> bool:
    """Drop rows too short or too generic to work as an exemplar."""
    if len(question) < _MIN_CHARS or len(answer) < _MIN_CHARS:
        return False
    return not _BOILERPLATE.search(question)


def _clean(questions, answers) -> tuple[list[str], list[str]]:
    """Zip and filter a corpus down to rows worth indexing."""
    kept_q: list[str] = []
    kept_a: list[str] = []
    for question, answer in zip(questions, answers, strict=True):
        if question and answer and _usable(question, answer):
            kept_q.append(question)
            kept_a.append(answer)

    dropped = len(questions) - len(kept_q)
    if dropped:
        logger.info("Filtered %d unusable rows of %d", dropped, len(questions))
    return kept_q, kept_a


@dataclass(frozen=True)
class Example:
    """A retrieved question/answer pair, correctly attributed."""

    question: str  # what the patient / help-seeker said
    answer: str  # what the doctor / counsellor replied
    score: float


class _Index:
    """A TF-IDF index over the question side of one corpus."""

    def __init__(self, questions: list[str], answers: list[str]) -> None:
        from sklearn.feature_extraction.text import TfidfVectorizer

        self._answers = answers
        self._questions = questions
        self._vectorizer = TfidfVectorizer(
            stop_words="english",
            max_features=50_000,
            ngram_range=(1, 2),
            # Dropping hapax terms denoises a large corpus, but on a small one
            # it prunes the whole vocabulary and raises. Scale it to the input.
            min_df=2 if len(questions) >= 50 else 1,
            sublinear_tf=True,
        )
        self._matrix = self._vectorizer.fit_transform(questions)

    def __len__(self) -> int:
        return len(self._questions)

    def search(self, query: str, top_k: int, min_score: float) -> list[Example]:
        from sklearn.metrics.pairwise import linear_kernel

        vector = self._vectorizer.transform([query])
        # Rows are L2-normalised by TfidfVectorizer, so the dot product is
        # already the cosine similarity.
        scores = linear_kernel(vector, self._matrix).ravel()
        if not scores.size:
            return []

        top_k = min(top_k, scores.size)
        # argpartition gets the top-k without fully sorting 20k scores.
        candidates = scores.argpartition(-top_k)[-top_k:]
        candidates = candidates[scores[candidates].argsort()[::-1]]

        return [
            Example(
                question=self._questions[i],
                answer=self._answers[i],
                score=float(scores[i]),
            )
            for i in candidates
            if scores[i] >= min_score
        ]


class KnowledgeBase:
    """Routes a question to a domain and retrieves supporting examples.

    Construction is deliberately fallible-but-safe: if the datasets cannot be
    downloaded the object still works, reporting ``ready is False`` and
    returning no examples, so the app degrades to general-assistant mode
    instead of failing to boot (which is what v1 did on any network error).
    """

    MENTAL_HEALTH_KEYWORDS = frozenset(
        {
            "anxious", "anxiety", "depressed", "depression", "stress", "stressed",
            "mental health", "counseling", "counselling", "therapy", "therapist",
            "feelings", "worthless", "suicidal", "suicide", "panic", "lonely",
            "grief", "trauma", "self-harm", "hopeless", "overwhelmed", "burnout",
        }
    )
    MEDICAL_KEYWORDS = frozenset(
        {
            "symptom", "symptoms", "diagnosis", "diagnose", "treatment", "doctor",
            "prescription", "medication", "pain", "illness", "disease", "infection",
            "surgery", "fever", "rash", "injury", "blood", "swelling", "nausea",
            "antibiotic", "vaccine", "dosage", "allergy", "cough",
        }
    )

    def __init__(self) -> None:
        self._indexes: dict[Domain, _Index] = {}
        self.ready = False

    # -- lifecycle -----------------------------------------------------

    def load(self, settings) -> None:
        """Download and index the corpora. Safe to call once at startup."""
        if not settings.enable_retrieval:
            logger.info("Retrieval disabled by configuration.")
            return

        loaders = (
            (Domain.MENTAL_HEALTH, self._load_mental_health),
            (Domain.MEDICAL, self._load_medical),
        )
        for domain, loader in loaders:
            try:
                questions, answers = loader(settings)
                self._indexes[domain] = _Index(questions, answers)
                logger.info(
                    "Indexed %d examples for %s", len(questions), domain.value
                )
            except Exception:
                # A missing corpus degrades quality, not availability.
                logger.exception("Could not index %s corpus", domain.value)

        self.ready = bool(self._indexes)

    def _load_medical(self, settings) -> tuple[list[str], list[str]]:
        from datasets import load_dataset

        rows = load_dataset(settings.medical_dataset, split="train")
        if len(rows) > settings.max_index_rows:
            rows = rows.select(range(settings.max_index_rows))
        # `input` is the patient, `output` is the doctor - v1 had these
        # the wrong way round.
        return _clean(rows["input"], rows["output"])

    def _load_mental_health(self, settings) -> tuple[list[str], list[str]]:
        from datasets import load_dataset

        rows = load_dataset(settings.mental_health_dataset, split="train")
        if len(rows) > settings.max_index_rows:
            rows = rows.select(range(settings.max_index_rows))
        # `Context` is the help-seeker, `Response` is the counsellor.
        return _clean(rows["Context"], rows["Response"])

    # -- querying ------------------------------------------------------

    @property
    def document_count(self) -> int:
        return sum(len(index) for index in self._indexes.values())

    def route(self, message: str) -> Domain:
        """Pick a domain by keyword vote, falling back to retrieval score.

        v1 used first-match-wins over two keyword lists. Counting hits means
        "I'm stressed about my surgery" lands in the domain with more support
        rather than whichever list happened to be checked first.
        """
        lowered = message.lower()
        mental = sum(1 for kw in self.MENTAL_HEALTH_KEYWORDS if kw in lowered)
        medical = sum(1 for kw in self.MEDICAL_KEYWORDS if kw in lowered)

        if mental or medical:
            return Domain.MENTAL_HEALTH if mental >= medical else Domain.MEDICAL

        # No keywords matched. Let the corpora vote with similarity instead,
        # so paraphrases that dodge the keyword lists still find context.
        best_domain, best_score = Domain.GENERAL, 0.0
        for domain, index in self._indexes.items():
            hits = index.search(message, top_k=1, min_score=0.0)
            if hits and hits[0].score > best_score:
                best_domain, best_score = domain, hits[0].score

        # Require clear support before claiming a specialist domain.
        return best_domain if best_score >= 0.25 else Domain.GENERAL

    def retrieve(self, message: str, domain: Domain, settings) -> list[Example]:
        index = self._indexes.get(domain)
        if index is None:
            return []
        return index.search(
            message, top_k=settings.top_k, min_score=settings.min_similarity
        )
