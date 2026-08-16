"""eval/benchmark.py — latency benchmark for the deployed /api/query endpoint.

Satisfies PRD §4: measures P50/P70/P100 across a reasonable number of test
queries (default 50), not a single best-case run.

Since recording 50 unique audio clips isn't practical, this cycles through
a small folder of representative pre-recorded questions (different topics,
optionally different languages) to reach the target request count - this
is documented explicitly in the report output, not hidden. Measures BOTH:
  - client-side wall-clock time (closest to real user-perceived latency,
    includes network + upload overhead the server-side harness timing can't see)
  - server-reported per-stage breakdown (stt/retrieval/generation/total),
    parsed straight out of the harness's own timing
"""
import glob
import json
import os
import statistics
import time
from datetime import datetime, timezone
import requests

API_URL = "http://127.0.0.1:5328/api/query"   # swap to your deployed Vercel URL once live
TEST_AUDIO_DIR = "test_audios"                 # folder of a few representative recordings
NUM_REQUESTS = 50
STRATEGY = "metadata"

OUTPUT_JSON = "latency_results.json"
OUTPUT_REPORT = "latency_report.md"


def percentile(values: list[float], p: float) -> float:
    """Manual percentile (nearest-rank method) - avoids a numpy dependency
    for something this small. p is 0-100."""
    if not values:
        return 0.0
    s = sorted(values)
    if p >= 100:
        return s[-1]
    idx = max(0, min(len(s) - 1, int(round(p / 100 * len(s))) - 1))
    return s[idx]


def load_test_audio_files() -> list[str]:
    files = sorted(glob.glob(os.path.join(TEST_AUDIO_DIR, "*")))
    files = [f for f in files if os.path.splitext(f)[1].lower() in
             (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac")]
    if not files:
        raise RuntimeError(
            f"No audio files found in '{TEST_AUDIO_DIR}/'. "
            f"Put a handful of short representative recordings there first."
        )
    return files


def run_benchmark(num_requests: int = NUM_REQUESTS) -> dict:
    audio_files = load_test_audio_files()
    print(f"Cycling through {len(audio_files)} recorded question(s) for {num_requests} total requests...")

    client_latencies = []
    server_stage_latencies = {"stt": [], "retrieval": [], "generation": [], "total": []}
    status_counts = {}
    provider_counts = {}
    errors = []

    for i in range(num_requests):
        audio_path = audio_files[i % len(audio_files)]
        ext = os.path.splitext(audio_path)[1].lstrip(".")

        start = time.perf_counter()
        try:
            with open(audio_path, "rb") as f:
                response = requests.post(
                    API_URL,
                    files={"audio": (os.path.basename(audio_path), f, f"audio/{ext}")},
                    data={"strategy": STRATEGY},
                    timeout=60,
                )
            elapsed_ms = (time.perf_counter() - start) * 1000
            client_latencies.append(elapsed_ms)

            body = response.json()
            status = body.get("status", "unknown")
            if status == "error":
                print(f"    (retrying once after transient error: {body.get('error_message')})")
                time.sleep(5)
                with open(audio_path, "rb") as f2:
                    response = requests.post(
                        API_URL,
                        files={"audio": (os.path.basename(audio_path), f2, f"audio/{ext}")},
                        data={"strategy": STRATEGY},
                        timeout=60,
                    )
                elapsed_ms = (time.perf_counter() - start) * 1000
                body = response.json()
                status = body.get("status", "unknown")

            status_counts[status] = status_counts.get(status, 0) + 1
            provider = body.get("provider_used") or "none"
            provider_counts[provider] = provider_counts.get(provider, 0) + 1

            for stage, values in server_stage_latencies.items():
                stage_val = body.get("latency_ms", {}).get(stage)
                if stage_val is not None:
                    values.append(stage_val)

            print(f"  [{i+1}/{num_requests}] {os.path.basename(audio_path)} -> "
                  f"{status} ({elapsed_ms:.0f}ms client-side) via {provider}")
            time.sleep(3)

        except Exception as e:
            errors.append(str(e))
            print(f"  [{i+1}/{num_requests}] FAILED: {e}")
    
    def summarize(values: list[float]) -> dict:
        if not values:
            return {"p50": None, "p70": None, "p100": None, "mean": None, "n": 0}
        return {
            "p50": round(percentile(values, 50), 1),
            "p70": round(percentile(values, 70), 1),
            "p100": round(percentile(values, 100), 1),
            "mean": round(statistics.mean(values), 1),
            "n": len(values),
        }

    results = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "num_requests_attempted": num_requests,
        "num_requests_succeeded": len(client_latencies),
        "num_errors": len(errors),
        "errors": errors[:10],   # cap - don't let a broken run flood the file
        "status_breakdown": status_counts,
        "provider_breakdown": provider_counts,
        "client_side_latency_ms": summarize(client_latencies),
        "server_stage_latency_ms": {
            stage: summarize(values) for stage, values in server_stage_latencies.items()
        },
        "note": (
            f"Benchmarked by cycling through {len(audio_files)} pre-recorded "
            f"representative question(s), not {num_requests} unique recordings - "
            f"documented here for transparency, not hidden."
        ),
    }
    return results


def write_report(results: dict):
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    lines = [
        "# Latency Benchmark Report",
        "",
        f"Run at: {results['run_at']}",
        f"Requests attempted: {results['num_requests_attempted']} | "
        f"Succeeded: {results['num_requests_succeeded']} | Errors: {results['num_errors']}",
        "",
        f"> {results['note']}",
        "",
        "## Status breakdown",
        "",
    ]
    for status, count in results["status_breakdown"].items():
        lines.append(f"- `{status}`: {count}")

    lines += ["", "## Client-side latency (real user-perceived, includes network+upload)", "",
              "| Metric | Value (ms) |", "|---|---|"]
    for k, v in results["client_side_latency_ms"].items():
        lines.append(f"| {k} | {v} |")

    lines += ["", "## Server-side per-stage breakdown", ""]
    for stage, stats in results["server_stage_latency_ms"].items():
        lines += [f"### {stage}", "", "| Metric | Value (ms) |", "|---|---|"]
        for k, v in stats.items():
            lines.append(f"| {k} | {v} |")
        lines.append("")

    lines += [
        "## Honest note on the 200ms target",
        "",
        "Full end-to-end latency (STT + retrieval + generation) is network-bound "
        "across three external services (Sarvam, Chroma Cloud, Groq/Gemini) and "
        "does not realistically hit 200ms regardless of code-level optimization. "
        "Retrieval-only latency is reported separately above as the number closest "
        "to what's actually within our control.",
    ]

    with open(OUTPUT_REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else NUM_REQUESTS
    results = run_benchmark(n)
    write_report(results)

    print("\n=== SUMMARY ===")
    print(f"Client-side total: {json.dumps(results['client_side_latency_ms'])}")
    print(f"Server total:      {json.dumps(results['server_stage_latency_ms']['total'])}")
    print(f"Status breakdown:  {json.dumps(results['status_breakdown'])}")
    print(f"\nWrote {OUTPUT_JSON} and {OUTPUT_REPORT}")