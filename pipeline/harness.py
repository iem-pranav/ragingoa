"""
pipeline/harness.py — orchestrates the full voice-RAG pipeline end to end:

  audio file -> STT -> input-safety gate -> retrieval -> confidence gate
  -> generation -> groundedness gate -> structured result

This is the "proper harness" the task brief asks for (§5): each stage is
isolated, failures are caught and logged rather than crashing, network
calls (STT, generation) get one retry, and the return value is always a
structured object - never a bare string - so the frontend/API layer has
a consistent shape to render regardless of which stage stopped things.
"""

import time
import traceback
from dataclasses import dataclass, field

from stt import transcribe, STTResult
from retrieve import retrieve, RetrievedChunk
from generate import generate_answer, GenerationResult
from guardrails import check_input_safety, check_retrieval_confidence, check_groundedness


@dataclass
class PipelineResult:
    # what actually happened, for the frontend to render + for eval logging
    status: str                      # "ok" | "blocked_unsafe_input" | "blocked_low_confidence" | "blocked_ungrounded" | "error"
    answer: str | None = None
    transcript: str | None = None
    detected_language: str | None = None
    sources: list[dict] = field(default_factory=list)   # [{text, similarity, metadata}]
    provider_used: str | None = None
    error_message: str | None = None
    latency_ms: dict = field(default_factory=dict)      # per-stage timings, feeds §7's latency report
    strategy_used: str = "metadata"


def _timed(label: str, timings: dict, fn, *args, **kwargs):
    """Runs fn, records its wall-clock time into timings[label], returns fn's result.
    One retry on any exception - this IS the harness's retry behavior."""
    start = time.perf_counter()
    try:
        result = fn(*args, **kwargs)
    except Exception as e:
        print(f"  [{label}] failed once ({e}), retrying...")
        start = time.perf_counter()  # restart the clock for the retry attempt
        result = fn(*args, **kwargs)  # if this also raises, it propagates up - caller's job to catch
    timings[label] = round((time.perf_counter() - start) * 1000, 1)
    return result


def run_pipeline(
    audio_path: str,
    strategy: str = "metadata",
    top_k: int = 3,
    stt_mode: str = "transcribe",
) -> PipelineResult:
    timings = {}
    overall_start = time.perf_counter()

    # ── Stage 1: STT ──────────────────────────────────────────────
    try:
        stt_result: STTResult = _timed("stt", timings, transcribe, audio_path, stt_mode)
    except Exception as e:
        return PipelineResult(
            status="error",
            error_message=f"STT failed: {e}",
            latency_ms=timings,
        )

    transcript = stt_result.transcript
    detected_language = stt_result.language_code

    # ── Stage 2: input safety gate ───────────────────────────────
    safety_check = check_input_safety(transcript)
    if not safety_check.passed:
        return PipelineResult(
            status="blocked_unsafe_input",
            answer="I can't help with that request.",
            transcript=transcript,
            detected_language=detected_language,
            latency_ms=timings,
        )

    # ── Stage 3: retrieval ────────────────────────────────────────
    try:
        chunks: list[RetrievedChunk] = _timed(
            "retrieval", timings, retrieve, transcript, strategy, top_k
        )
    except Exception as e:
        return PipelineResult(
            status="error",
            transcript=transcript,
            detected_language=detected_language,
            error_message=f"Retrieval failed: {e}",
            latency_ms=timings,
        )

    # ── Stage 4: retrieval-confidence gate (doubles as off-topic filter) ──
    confidence_check = check_retrieval_confidence(chunks)
    if not confidence_check.passed:
        return PipelineResult(
            status="blocked_low_confidence",
            answer="I don't have enough grounded information to answer that confidently.",
            transcript=transcript,
            detected_language=detected_language,
            sources=[{"text": c.text, "similarity": c.similarity, "metadata": c.metadata} for c in chunks],
            latency_ms=timings,
            strategy_used=strategy,
        )

    # ── Stage 5: generation ──────────────────────────────────────
    context_texts = [c.text for c in chunks]
    try:
        gen_result: GenerationResult = _timed(
            "generation", timings, generate_answer, transcript, context_texts
        )
    except Exception as e:
        return PipelineResult(
            status="error",
            transcript=transcript,
            detected_language=detected_language,
            sources=[{"text": c.text, "similarity": c.similarity, "metadata": c.metadata} for c in chunks],
            error_message=f"Generation failed (both providers): {e}",
            latency_ms=timings,
            strategy_used=strategy,
        )

    # ── Stage 6: groundedness gate ───────────────────────────────
    groundedness_check = check_groundedness(gen_result.answer, context_texts)
    timings["total"] = round((time.perf_counter() - overall_start) * 1000, 1)

    if not groundedness_check.passed:
        # graceful degradation per PRD §4: don't discard the work, hand back
        # the raw retrieved chunks with a disclaimer instead of a silent fail
        return PipelineResult(
            status="blocked_ungrounded",
            answer=(
                "I found related information but couldn't produce a fully grounded answer. "
                "Here's what was retrieved:\n\n" + "\n\n".join(context_texts[:3])
            ),
            transcript=transcript,
            detected_language=detected_language,
            sources=[{"text": c.text, "similarity": c.similarity, "metadata": c.metadata} for c in chunks],
            provider_used=gen_result.provider_used,
            latency_ms=timings,
            strategy_used=strategy,
        )

    return PipelineResult(
        status="ok",
        answer=gen_result.answer,
        transcript=transcript,
        detected_language=detected_language,
        sources=[{"text": c.text, "similarity": c.similarity, "metadata": c.metadata} for c in chunks],
        provider_used=gen_result.provider_used,
        latency_ms=timings,
        strategy_used=strategy,
    )


if __name__ == "__main__":
    import sys
    import json

    audio_path = sys.argv[1] if len(sys.argv) > 1 else "test_audio.mp3"
    result = run_pipeline(audio_path)

    print(f"\nstatus: {result.status}")
    print(f"transcript: {result.transcript!r}  (lang: {result.detected_language})")
    print(f"answer: {result.answer}")
    print(f"provider: {result.provider_used}")
    print(f"latency_ms: {json.dumps(result.latency_ms, indent=2)}")
    print(f"num_sources: {len(result.sources)}")