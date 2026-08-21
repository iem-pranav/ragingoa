# VaniRAGA 

Voice-enabled Retrieval-Augmented Generation system. Speak or type a question in English, Hindi, Marathi, or Tamil — it's transcribed (for voice input), matched against a retrieval index built from the MS MARCO-XI dataset, and answered with an LLM grounded strictly in the retrieved passages.

**Live:** https://vanirag.vercel.app
**Repo:** https://github.com/iem-pranav/vanirag

---

## What it does
1. Ask a question — by voice (recorded in-browser) or by typing.
2. For voice input, **speech-to-text** (Sarvam Saaras v3) transcribes it, auto-detecting the spoken language.
3. The query is embedded and matched against a **Chroma Cloud** vector index built from `ai4bharat/MSMARCO-XI`.
4. Retrieved passages are checked for confidence — if nothing relevant enough comes back, the system says so instead of guessing.
5. An LLM (Groq, with a Gemini fallback) generates an answer **grounded only in the retrieved context**.
6. The generated answer is checked for groundedness before being shown — if it drifts from the source material, the system flags it rather than presenting it as confident.
7. The answer is shown immediately; full retrieval sources and a per-stage latency breakdown are available on demand behind a details panel, kept out of the main flow.

---

## Architecture
```text
Browser (mic recording or typed text)
    │
    ▼
Next.js frontend (Vercel)
    │  POST /api/query (audio file OR text field)
    ▼
Flask backend — single Vercel Python serverless function
    │
    ├─ 1. STT (voice only)  → Sarvam Saaras v3 API
    ├─ 2. Guardrail          → input safety screen
    ├─ 3. Retrieval          → Chroma Cloud (multilingual-e5-small embeddings)
    ├─ 4. Guardrail          → retrieval-confidence gate
    ├─ 5. Generation         → Groq (primary) → Gemini (fallback)
    ├─ 6. Guardrail          → groundedness check
    └─ 7. Response           → structured JSON: answer, sources, per-stage latency
```
Everything from step 2 onward runs inside a single orchestrating function (`pipeline/harness.py`) — not a bare prompt-in/text-out call. Each stage is isolated, timed independently, and retried once on transient failure before the whole request is allowed to fail. The text-input path shares the same guardrail → retrieval → generation chain as voice, skipping only the STT step.

---

## Tech stack
| Layer | Choice |
|---|---|
| Frontend | Next.js (TypeScript), Tailwind CSS |
| Backend | Python, Flask, deployed as a Vercel serverless function |
| Speech-to-text | Sarvam AI — Saaras v3 |
| Vector database | Chroma Cloud |
| Embedding model | `intfloat/multilingual-e5-small` |
| Generation (primary) | Groq — `gpt-oss-20b` |
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
2. **Semantic (adaptive breakpoints)** — sentences are embedded, and chunk boundaries are placed at the largest embedding-distance jumps between consecutive sentences. The breakpoint threshold is computed **per document** as a percentile of that document's own sentence-to-sentence distances, rather than a single fixed number — since embedding similarity scores don't sit on one universal scale across documents, an adaptive threshold avoids systematically over- or under-splitting. Sentence embedding is batched across the full document set in one pass for efficiency.
3. **Metadata-aware (passage-level)** — each original MS MARCO passage is preserved as its own chunk, tagged with its source query, query type, and the dataset's own `is_selected` ground-truth relevance flag. This keeps the passage as the retrieval unit MS MARCO itself was designed around, and enables retrieval-accuracy evaluation against the dataset's own labels.

All three strategies are indexed into separate Chroma collections and are independently queryable; the deployed system defaults to the metadata-aware collection for generation.

---

## Guardrails
| Check | Stage | Behavior |
|---|---|---|
| Unsafe input | Before retrieval | Pattern-screens the query for clearly unsafe requests; refuses immediately without calling retrieval or generation |
| Low retrieval confidence | After retrieval, before generation | If the best-matching chunk's similarity falls below threshold, generation is skipped entirely and the system states it doesn't have grounded information — this also functions as an off-topic filter |
| Groundedness | After generation | Checks what fraction of the generated answer's meaningful words actually appear in the retrieved context. If grounding is too low, the raw retrieved passages are returned with a disclaimer instead of presenting an unverified answer as confident |

The system is explicitly designed to know when *not* to answer, not just how to answer.

---

## Latency
**Retrieval + generation** — the portion of the pipeline that runs within this system's own infrastructure — is the number reported here as the core pipeline latency figure:
| Stage | Typical (ms), warm instance |
|---|---|
| Retrieval | ~90 |
| Generation | ~550 |
| **Retrieval + generation** | **~640** |

Speech-to-text is a required, separate external API call for voice input (~1,900ms typical) and is reported independently rather than folded into the pipeline figure above, since it is not part of this system's own retrieval/generation logic.

**Full end-to-end P50 / P70 / P100** (n=50 real queries against the live production deployment, including STT):
| Metric | Server-side (ms) |
|---|---|
| P50 | 2,180.4 |
| P70 | 2,411.3 |
| P100 | 8,754.2 |
| Mean | 2,322.6 |

Full methodology and raw results: [`eval/latency_report.md`](./eval/latency_report.md), generated by [`eval/benchmark.py`](./eval/benchmark.py).

---

## Project structure
```text
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
python index.py          # runs on [http://127.0.0.1:5328](http://127.0.0.1:5328)

# Frontend (separate terminal)
npm install
npm run dev               # runs on http://localhost:3000
```

Requires a `.env` file in the project root with:
```text
SARVAM_API_KEY=
CHROMA_API_KEY=
GROQ_API_KEY=
GEMINI_API_KEY=
HF_TOKEN=
```

---

## Author
Pranav Khairnar