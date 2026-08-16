"""
pipeline/guardrails.py — safety and grounding checks around the model.

Per PRD §6:
  - Pre-generation: low retrieval confidence -> skip generation entirely
    (this doubles as the off-topic filter: an off-topic question simply
    won't retrieve anything similar, so the same check catches both cases)
  - Pre-generation: basic unsafe-input screen on the transcript
  - Post-generation: groundedness check - do the answer's claims actually
    trace back to the retrieved context, or did the model add things?

These are deliberately lightweight, explainable heuristics (word-overlap,
keyword screening) rather than a second LLM call for judging - keeps the
pipeline fast and avoids "using an LLM to guardrail an LLM" circularity
for a hackathon-scale system. Documented as a known simplification; a
production system would likely add a moderation API call here too.
"""

import re
from dataclasses import dataclass, field
from typing import Protocol

# Duck-typed instead of importing RetrievedChunk from retrieve.py directly -
# keeps this module's only dependencies as Python stdlib, so guardrail logic
# can be unit-tested/run without pulling in chromadb + sentence-transformers.
class HasSimilarity(Protocol):
    similarity: float

# ── Config ────────────────────────────────────────────────────────
MIN_RETRIEVAL_SIMILARITY = 0.60   # below this top-chunk similarity -> treat as off-topic/no-info
MIN_GROUNDEDNESS_RATIO = 0.35     # fraction of answer's content words that must appear in context

# Small, generic unsafe-input keyword screen. NOT exhaustive or a substitute
# for a real moderation API - documented as a lightweight first line of
# defense, catching the most obvious cases (self-harm, violence, illegal
# activity requests) rather than every possible category.
UNSAFE_PATTERNS = [
    r"\bhow to (make|build|create) (a )?(bomb|weapon|explosive)\b",
    r"\bhow to (kill|murder|hurt) (myself|someone|a person)\b",
    r"\bsuicide method\b",
    r"\bhow to hack\b",
    r"\bchild (abuse|exploitation)\b",
]
_UNSAFE_RE = [re.compile(p, re.IGNORECASE) for p in UNSAFE_PATTERNS]

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "in", "on", "at", "to",
    "for", "and", "or", "but", "with", "as", "by", "this", "that", "it", "its",
    "be", "has", "have", "had", "not", "no", "do", "does", "did", "can", "will",
    "would", "should", "could", "may", "might", "than", "then", "so", "such",
}


@dataclass
class GuardrailResult:
    passed: bool
    reason: str = ""
    details: dict = field(default_factory=dict)


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z\u0900-\u097F\u0B80-\u0BFF]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def check_input_safety(query_text: str) -> GuardrailResult:
    """Screens the transcribed query BEFORE retrieval/generation ever runs."""
    for pattern in _UNSAFE_RE:
        if pattern.search(query_text):
            return GuardrailResult(
                passed=False,
                reason="unsafe_input",
                details={"matched_pattern": pattern.pattern},
            )
    return GuardrailResult(passed=True)


def check_retrieval_confidence(
    chunks: list[HasSimilarity], min_similarity: float = MIN_RETRIEVAL_SIMILARITY
) -> GuardrailResult:
    """
    Gate BEFORE generation: if even the best-matching chunk isn't similar
    enough, there's nothing grounded to answer from - covers both genuinely
    off-topic questions and topics simply missing from our sampled index.
    """
    if not chunks:
        return GuardrailResult(passed=False, reason="no_chunks_retrieved")

    top_similarity = max(c.similarity for c in chunks)
    if top_similarity < min_similarity:
        return GuardrailResult(
            passed=False,
            reason="low_retrieval_confidence",
            details={"top_similarity": round(top_similarity, 3), "threshold": min_similarity},
        )
    return GuardrailResult(passed=True, details={"top_similarity": round(top_similarity, 3)})


def check_groundedness(
    answer: str, context_chunks: list[str], min_ratio: float = MIN_GROUNDEDNESS_RATIO
) -> GuardrailResult:
    """
    Gate AFTER generation: what fraction of the answer's meaningful words
    actually appear somewhere in the retrieved context? Low overlap suggests
    the model drifted into its own knowledge instead of the provided context.

    This is intentionally simple (word-overlap, not semantic entailment) -
    fast, dependency-free, and explainable in a README/demo, at the cost of
    being fooled by paraphrasing. Documented trade-off, not an oversight.
    """
    answer_words = _tokenize(answer)
    if not answer_words:
        return GuardrailResult(passed=True, details={"ratio": 1.0})  # nothing to check

    context_words = set()
    for c in context_chunks:
        context_words |= _tokenize(c)

    overlap = answer_words & context_words
    ratio = len(overlap) / len(answer_words)

    if ratio < min_ratio:
        return GuardrailResult(
            passed=False,
            reason="low_groundedness",
            details={"ratio": round(ratio, 3), "threshold": min_ratio},
        )
    return GuardrailResult(passed=True, details={"ratio": round(ratio, 3)})


if __name__ == "__main__":
    # Quick manual tests, no API calls needed
    print("-- input safety --")
    print(check_input_safety("what is the capital of india"))
    print(check_input_safety("how to make a bomb at home"))

    print("\n-- retrieval confidence (fake chunks) --")

    class FakeChunk:
        def __init__(self, sim):
            self.similarity = sim

    print(check_retrieval_confidence([FakeChunk(0.91), FakeChunk(0.80)]))
    print(check_retrieval_confidence([FakeChunk(0.42)]))

    print("\n-- groundedness --")
    ctx = ["Biotechnology encompasses procedures for modifying living organisms."]
    print(check_groundedness("Biotechnology involves modifying living organisms for human use.", ctx))
    print(check_groundedness("The moon landing happened in 1969 and Neil Armstrong walked on it.", ctx))