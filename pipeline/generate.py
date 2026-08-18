"""
pipeline/generate.py — answer generation from retrieved chunks.
Primary: Groq (fast). Fallback: Gemini Flash, used automatically if Groq
fails or errors (matches PRD §3: "swappable" generation provider).

This module does NOT do retrieval or guardrail checks itself - it only
takes chunks you already retrieved and turns them into a grounded answer.
Guardrail decisions (whether to even call this, and whether to trust its
output) live in pipeline/guardrails.py + pipeline/harness.py, next.
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv
from groq import Groq
from groq import APIError as GroqAPIError
from google import genai as google_genai

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY not found - check your .env file")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY not found - check your .env file")

# GROQ_MODEL = "llama-3.1-8b-instant"
GROQ_MODEL = "openai/gpt-oss-20b"
GEMINI_MODEL = "gemini-3.7-flash"   # pinned version, not a "-latest" alias (those can silently change under you)

_groq_client = Groq(api_key=GROQ_API_KEY, max_retries=0)
_gemini_client = google_genai.Client(api_key=GEMINI_API_KEY)


@dataclass
class GenerationResult:
    answer: str
    provider_used: str    # "groq" or "gemini" - useful for your latency/eval logging later
    model_used: str


SYSTEM_PROMPT = (
    "You are a factual assistant that answers ONLY using the provided context. "
    "Rules:\n"
    "1. If the context does not contain enough information to answer, say so "
    "plainly instead of guessing or using outside knowledge.\n"
    "2. Keep answers concise - 2-4 sentences unless the question needs more.\n"
    "3. Do not fabricate facts, numbers, or sources not present in the context.\n"
    "4. Answer in the same language the question was asked in, when possible."
)


def _build_prompt(query: str, context_chunks: list[str]) -> str:
    context_block = "\n\n".join(f"[Context {i+1}]\n{c}" for i, c in enumerate(context_chunks))
    return (
        f"Context:\n{context_block}\n\n"
        f"Question: {query}\n\n"
        f"Answer using only the context above."
    )


def _generate_groq(prompt: str) -> str:
    response = _groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,   # low temperature - we want grounded, not creative
        max_tokens=400,
    )
    return response.choices[0].message.content


def _generate_gemini(prompt: str) -> str:
    response = _gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config={"system_instruction": SYSTEM_PROMPT, "temperature": 0.2, "max_output_tokens": 200},
    )
    return response.text


def generate_answer(query: str, context_chunks: list[str]) -> GenerationResult:
    """
    Tries Groq first (fast path). On any failure, falls back to Gemini
    automatically - this IS the harness-level retry/fallback behavior the
    PRD calls for at the generation step specifically.
    """
    prompt = _build_prompt(query, context_chunks)

    try:
        answer = _generate_groq(prompt)
        return GenerationResult(answer=answer, provider_used="groq", model_used=GROQ_MODEL)
    except GroqAPIError as e:
        print(f"  Groq failed ({e}), falling back to Gemini...")
    except Exception as e:
        print(f"  Groq failed unexpectedly ({e}), falling back to Gemini...")

    try:
        answer = _generate_gemini(prompt)
        return GenerationResult(answer=answer, provider_used="gemini", model_used=GEMINI_MODEL)
    except Exception as e:
        raise RuntimeError(f"Both Groq and Gemini generation failed. Last error: {e}") from e


if __name__ == "__main__":
    # Quick manual test with fake context, no retrieval needed
    import sys
    query = " ".join(sys.argv[1:]) or "What is biotechnology?"
    fake_context = [
        "Biotechnology encompasses a wide range of procedures for modifying "
        "living organisms according to human purposes, going back to domestication "
        "of animals, cultivation of plants, and improvements to these through "
        "artificial selection and hybridization."
    ]
    result = generate_answer(query, fake_context)
    print(f"[{result.provider_used} / {result.model_used}]")
    print(result.answer)