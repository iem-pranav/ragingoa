# RAGInGoa

A voice-enabled Retrieval-Augmented Generation system. Speak a question in English, Hindi, Marathi, or Tamil — it's transcribed, matched against a retrieval index built from the MS MARCO-XI dataset, and answered with an LLM grounded strictly in the retrieved passages.

Built for **HH Goa 2026 — Shortlisting Task 2**.

**Live:** https://ragingoa-ecru.vercel.app
**Repo:** https://github.com/iem-pranav/ragingoa

---

## What it does

1. You record a voice question in the browser.
2. **Speech-to-text** (Sarvam Saaras v3) transcribes it, auto-detecting the spoken language.
3. The transcript is embedded and matched against a **Chroma Cloud** vector index built from `ai4bharat/MSMARCO-XI`.
4. Retrieved passages are checked for confidence — if nothing relevant enough comes back, the system says so instead of guessing.
5. An LLM (Groq, with a Gemini fallback) generates an answer **grounded only in the retrieved context**.
6. The generated answer is checked for groundedness before being shown — if it drifts from the source material, the system flags it rather than presenting it as confident.
7. The full response — answer, sources, per-stage latency — is returned and rendered live in the UI.

---

## Architecture

```
Browser (mic recording)
    │
    ▼
Next.js frontend (Vercel)
    │  POST /api/query (audio file)
    ▼
Flask backend — single Vercel Python serverless function
    │
    ├─ 1. STT           → Sarvam Saaras v3 API
    ├─ 2. Guardrail      → input safety screen
    ├─ 3. Retrieval      → Chroma Cloud (multilingual-e5-small embeddings)
    ├─ 4. Guardrail      → retrieval-confidence gate
    ├─ 5. Generation     → Groq (primary) → Gemini (fallback)
    ├─ 6. Guardrail      → groundedness check
    └─ 7. Response       → structured JSON: answer, sources, per-stage latency
```

Everything from step 1 onward runs inside a single orchestrating function (`pipeline/harness.py`) — not a bare prompt-in/text-out call. Each stage is isolated, timed independently, and retried once on transient failure before the whole request is allowed to fail.

---

## Tech stack

| Layer | Choice |
|---|---|
| Frontend | Next.js (TypeScript), Tailwind CSS |
| Backend | Python, Flask, deployed as a Vercel serverless function |
| Speech-to-text | Sarvam AI — Saaras v3 |
| Vector database | Chroma Cloud |
| Embedding model | `intfloat/multilingual-e5-small` |
| Generation (primary) | Groq — `gpt-oss-20b` (fastest inference tier available on Groq as of this build) |
| Generation (fallback) | Google Gemini — `gemini-3.7-flash` |
| Deployment | Vercel (single project, frontend + backend) |

---

## Dataset & indexing

**Source:** [`ai4bharat/MSMARCO-XI`](https://huggingface.co/datasets/ai4bharat/MSMARCO-XI) — MS MARCO passages translated/aligned across Indian languages, validation split.

**Languages indexed:** Hindi, Marathi, Tamil, plus English (derived from the same rows' English-language fields).

**Chunk counts by strategy** (final index):

| Strategy | Chunks |
|---|---|
| Fixed-overlap | 51,813 |
| Semantic (adaptive) | 58,360 |
| Metadata-aware | 59,740 |

### Chunking strategies

Three distinct strategies were implemented and indexed in parallel — not a single naive fixed-size splitter:

1. **Fixed-size with overlap** — baseline chunking at 500 characters with 100-character overlap between consecutive chunks, so no sentence boundary is ever silently cut without adjacent context on either side.

2. **Semantic (adaptive breakpoints)** — sentences are embedded, and chunk boundaries are placed at the largest embedding-distance jumps between consecutive sentences. The breakpoint threshold is computed **per document** as a percentile of that document's own sentence-to-sentence distances, rather than a single fixed number — since embedding similarity scores don't sit on one universal scale across documents, an adaptive threshold avoids systematically over- or under-splitting. Sentence embedding is batched across the full document set in one pass for efficiency, not computed one document at a time.

3. **Metadata-aware (passage-level)** — each original MS MARCO passage is preserved as its own chunk, tagged with its source query, query type, and the dataset's own `is_selected` ground-truth relevance flag. This keeps the passage as the retrieval unit MS MARCO itself was designed around, and the `is_selected` flag enables retrieval-accuracy evaluation against the dataset's own labels.

All three strategies are indexed into separate Chroma collections (`rag_chunks_fixed`, `rag_chunks_semantic`, `rag_chunks_metadata`) and are independently queryable; the deployed system defaults to the metadata-aware collection for generation.

---

## Guardrails

| Check | Stage | Behavior |
|---|---|---|
| Unsafe input | Before retrieval | Pattern-screens the transcript for clearly unsafe requests (e.g. weapons, self-harm, hacking); refuses immediately without calling retrieval or generation |
| Low retrieval confidence | After retrieval, before generation | If the best-matching chunk's similarity falls below threshold, generation is skipped entirely and the system states it doesn't have grounded information — this also functions as the off-topic filter, since an off-topic question simply won't retrieve anything similar |
| Groundedness | After generation | Checks what fraction of the generated answer's meaningful words actually appear in the retrieved context. If grounding is too low, the raw retrieved passages are returned with a disclaimer instead of presenting an unverified answer as confident |

The system is explicitly designed to know when *not* to answer, not just how to answer.

---

## Latency

The task's 200ms target is scoped to **retrieval** — the one stage that runs entirely within our own infrastructure. Speech-to-text and LLM generation are separate, mandatory external API calls (STT is a required part of the task's own technical spec) and are reported as their own distinct stages rather than folded into the same number, consistent with how latency budgets are typically framed for pipelines built on third-party inference APIs.

**Representative per-stage timings (warm instance):**

| Stage | Typical (ms) | Notes |
|---|---|---|
| Speech-to-text | ~1,900 | Sarvam API round-trip; required by task spec, not self-hostable |
| Retrieval | ~90 | Chroma Cloud query, warm instance — the stage actually comparable to the 200ms target |
| Generation | ~550 | Groq (`gpt-oss-20b`, fastest available tier on the platform), Gemini fallback |

**Full-pipeline P50 / P70 / P100** (n=50 real end-to-end voice queries against the live production deployment):

| Metric | Client-side (ms) | Server-side (ms) |
|---|---|---|
| P50 | 3,717.0 | 2,180.4 |
| P70 | 3,889.1 | 2,411.3 |
| P100 | 31,517.8 | 8,754.2 |
| Mean | 4,103.2 | 2,322.6 |

Status breakdown: 45 `ok`, 5 `blocked_ungrounded` (guardrail correctly withheld an unverified answer), 0 errors.

Client-side vs. server-side numbers are both reported deliberately: the ~1,500ms gap between them is network transfer time for the audio upload and response, external to the pipeline itself.

**On the P100 outlier:** this reflects a single cold serverless-function instance out of 50 requests (~2% of traffic). On a cold instance, the embedding model is loaded into memory once; every subsequent request on the same warm instance does not repeat this cost. Two independent 50-query runs produced consistent P100 values (~30.7s and ~31.5s), confirming this is a understood, repeatable characteristic of serverless cold starts rather than an intermittent fault. P50/P70 reflect what the large majority of real interactions experience.

Full methodology and raw results: [`eval/latency_report.md`](./eval/latency_report.md), generated by [`eval/benchmark.py`](./eval/benchmark.py).

---

## Project structure

```
/indexing       → dataset sampling, 3 chunking strategies, embedding, Chroma Cloud upload (Colab)
/pipeline       → stt.py, retrieve.py, generate.py, guardrails.py, harness.py
/api            → Flask app (index.py) — deployed as the Vercel Python serverless function
/app            → Next.js frontend
/eval           → latency benchmark script + results
vercel.json     → routes /api/* to the Python function; function config
```

---

## Running locally

```bash
# Backend
cd api
pip install -r ../requirements.txt
python index.py          # runs on http://127.0.0.1:5328

# Frontend (separate terminal)
npm install
npm run dev               # runs on http://localhost:3000
```

Requires a `.env` file in the project root with:
```
SARVAM_API_KEY=
CHROMA_API_KEY=
GROQ_API_KEY=
GEMINI_API_KEY=
HF_TOKEN=
```

---

## Team

Pranav Khairnar
