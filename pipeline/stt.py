"""
pipeline/stt.py — Sarvam Saaras v3 speech-to-text wrapper.

Synchronous REST endpoint: audio files up to 30 seconds only. For longer
recordings you'd need Sarvam's Batch API instead - fine for this project
since voice questions are short.
"""

import os
from dotenv import load_dotenv
from sarvamai import SarvamAI
from sarvamai.core.api_error import ApiError

load_dotenv()  # reads .env in project root

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
if not SARVAM_API_KEY:
    raise RuntimeError("SARVAM_API_KEY not found - check your .env file")

_client = SarvamAI(api_subscription_key=SARVAM_API_KEY)


class STTResult:
    """Small typed wrapper so callers don't depend on the raw SDK response shape."""
    def __init__(self, transcript: str, language_code: str | None, request_id: str):
        self.transcript = transcript
        self.language_code = language_code   # e.g. "hi-IN", or None if undetected
        self.request_id = request_id

    def __repr__(self):
        return f"STTResult(transcript={self.transcript!r}, language_code={self.language_code!r})"


def transcribe(audio_path: str, mode: str = "transcribe", max_retries: int = 2) -> STTResult:
    """
    Transcribes a short (<=30s) audio file using Saaras v3.

    mode: "transcribe" (original language) or "translate" (-> English).
          We use "transcribe" for the RAG pipeline so retrieval can match
          against native-language chunks too, not just English ones.

    Raises RuntimeError with a clear message on failure (bad key, bad audio,
    rate limit, etc.) — caller (the harness) decides how to handle that,
    this function's job is just to talk to Sarvam and fail loudly and clearly.
    """
    if not os.path.exists(audio_path):
        raise RuntimeError(f"Audio file not found: {audio_path}")
    if os.path.getsize(audio_path) == 0:
        raise RuntimeError(f"Audio file is empty: {audio_path}")

    last_error = None
    for attempt in range(1, max_retries + 2):  # e.g. max_retries=2 -> 3 total attempts
        try:
            with open(audio_path, "rb") as f:
                response = _client.speech_to_text.transcribe(
                    file=f,
                    model="saaras:v3",
                    mode=mode,
                )
            return STTResult(
                transcript=response.transcript,
                language_code=getattr(response, "language_code", None),
                request_id=getattr(response, "request_id", ""),
            )
        except ApiError as e:
            last_error = e
            if e.status_code == 403:
                # bad API key - retrying won't help, fail immediately
                raise RuntimeError("Sarvam auth failed - check SARVAM_API_KEY in .env") from e
            if e.status_code == 422:
                # bad audio (too long, bad format) - retrying won't help either
                raise RuntimeError(
                    f"Sarvam rejected the audio (likely >30s or unsupported format): {e.body}"
                ) from e
            if e.status_code in (429, 503) and attempt <= max_retries:
                # rate limited / overloaded - worth a retry
                print(f"  Sarvam busy (status {e.status_code}), retry {attempt}/{max_retries}...")
                continue
            raise RuntimeError(f"Sarvam STT failed (status {e.status_code}): {e.body}") from e
        except Exception as e:
            last_error = e
            if attempt <= max_retries:
                print(f"  STT error, retry {attempt}/{max_retries}: {e}")
                continue
            raise RuntimeError(f"Sarvam STT failed after {max_retries} retries: {e}") from e

    raise RuntimeError(f"Sarvam STT failed: {last_error}")


if __name__ == "__main__":
    # Quick manual test: put a short WAV/MP3 file at pipeline/test_audio.wav
    # and run: python pipeline/stt.py
    import sys
    test_file = sys.argv[1] if len(sys.argv) > 1 else "test_audio.wav"
    result = transcribe(test_file)
    print(result)