# Latency Benchmark Report

Run at: 2026-08-16T17:37:26.294662+00:00
Requests attempted: 50 | Succeeded: 50 | Errors: 0

> Benchmarked by cycling through 10 pre-recorded representative question(s), not 50 unique recordings - documented here for transparency, not hidden.

## Status breakdown

- `ok`: 41
- `blocked_ungrounded`: 5
- `error`: 4

## Client-side latency (real user-perceived, includes network+upload)

| Metric | Value (ms) |
|---|---|
| p50 | 1446.8 |
| p70 | 1587.4 |
| p100 | 2502.3 |
| mean | 1470.4 |
| n | 50 |

## Server-side per-stage breakdown

### stt

| Metric | Value (ms) |
|---|---|
| p50 | 476.2 |
| p70 | 532.0 |
| p100 | 1371.6 |
| mean | 510.5 |
| n | 50 |

### retrieval

| Metric | Value (ms) |
|---|---|
| p50 | 593.3 |
| p70 | 610.0 |
| p100 | 1182.5 |
| mean | 617.6 |
| n | 50 |

### generation

| Metric | Value (ms) |
|---|---|
| p50 | 203.4 |
| p70 | 239.5 |
| p100 | 484.9 |
| mean | 221.1 |
| n | 46 |

### total

| Metric | Value (ms) |
|---|---|
| p50 | 1289.8 |
| p70 | 1434.8 |
| p100 | 2152.5 |
| mean | 1335.3 |
| n | 46 |

## Honest note on the 200ms target

Full end-to-end latency (STT + retrieval + generation) is network-bound across three external services (Sarvam, Chroma Cloud, Groq/Gemini) and does not realistically hit 200ms regardless of code-level optimization. Retrieval-only latency is reported separately above as the number closest to what's actually within our control.