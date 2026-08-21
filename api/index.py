# """
# api/index.py — Flask backend, deployed as a single Vercel Python
# serverless function. Vercel auto-detects a Flask instance named `app`
# at this path (api/index.py) and mounts it under /api/* — this is what
# makes the "one Vercel deployment, no separate Render backend" setup work.

# Wraps pipeline/harness.py as an HTTP endpoint. Does NOT reimplement any
# pipeline logic - this file's only job is: receive an audio upload, hand
# it to the harness, return the harness's structured result as JSON.
# """

# import os
# import sys
# import tempfile
# import time
# from dataclasses import asdict

# from flask import Flask, request, jsonify

# # pipeline/ sits one level up from api/ - make it importable without
# # restructuring the project or duplicating code into api/
# sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

# from harness import run_pipeline  # noqa: E402  (must come after sys.path insert)

# app = Flask(__name__)

# ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".webm"}
# MAX_AUDIO_BYTES = 15 * 1024 * 1024   # 15MB safety cap - Sarvam's sync endpoint caps at 30s audio anyway


# @app.route("/api/health", methods=["GET"])
# def health():
#     """Cheap endpoint to confirm the function is alive and imports worked -
#     hit this first when debugging a deploy before testing the real endpoint."""
#     return jsonify({"status": "ok"})


# @app.route("/api/query", methods=["POST"])
# def query():
#     """
#     Expects multipart/form-data with:
#       - "audio": the audio file (required)
#       - "strategy": "fixed" | "semantic" | "metadata" (optional, defaults to "metadata")

#     Returns the harness's PipelineResult as JSON, plus a request-level
#     "request_latency_ms" that includes upload/parsing overhead the harness
#     itself can't see - useful for your P50/P70/P100 report since it's
#     closer to what a real user experiences than the harness's internal timing alone.
#     """
#     request_start = time.perf_counter()

#     if "audio" not in request.files:
#         return jsonify({"status": "error", "error_message": "No 'audio' file in request"}), 400

#     audio_file = request.files["audio"]
#     if audio_file.filename == "":
#         return jsonify({"status": "error", "error_message": "Empty filename"}), 400

#     ext = os.path.splitext(audio_file.filename)[1].lower()
#     if ext not in ALLOWED_EXTENSIONS:
#         return jsonify({
#             "status": "error",
#             "error_message": f"Unsupported audio format '{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
#         }), 400

#     strategy = request.form.get("strategy", "metadata")
#     if strategy not in ("fixed", "semantic", "metadata"):
#         return jsonify({"status": "error", "error_message": f"Invalid strategy '{strategy}'"}), 400

#     # Vercel functions get a writable /tmp - save the upload there, always
#     # clean up in `finally` so failed requests don't leak files across invocations
#     tmp_path = None
#     try:
#         with tempfile.NamedTemporaryFile(suffix=ext, delete=False, dir=tempfile.gettempdir()) as tmp:
#             audio_file.save(tmp.name)
#             tmp_path = tmp.name

#         if os.path.getsize(tmp_path) > MAX_AUDIO_BYTES:
#             return jsonify({"status": "error", "error_message": "Audio file too large (max 15MB)"}), 400

#         result = run_pipeline(tmp_path, strategy=strategy)
#         result_dict = asdict(result)
#         result_dict["request_latency_ms"] = round((time.perf_counter() - request_start) * 1000, 1)

#         return jsonify(result_dict), 200

#     except Exception as e:
#         return jsonify({
#             "status": "error",
#             "error_message": f"Unexpected server error: {e}",
#             "request_latency_ms": round((time.perf_counter() - request_start) * 1000, 1),
#         }), 500

#     finally:
#         if tmp_path and os.path.exists(tmp_path):
#             os.remove(tmp_path)


# if __name__ == "__main__":
#     # Local dev only - Vercel doesn't run this block, it imports `app` directly
#     app.run(port=5328, debug=True)

"""
api/index.py — Flask backend, deployed as a single Vercel Python
serverless function. Handles two input modes on the same endpoint:
multipart audio (voice) or a plain "text" form field (typed query) -
both flow through the same harness/guardrails/generation path.
"""

import os
import sys
import tempfile
import time
from dataclasses import asdict

from flask import Flask, request, jsonify

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

from harness import run_pipeline, run_pipeline_from_text  # noqa: E402

app = Flask(__name__)

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".webm"}
MAX_AUDIO_BYTES = 15 * 1024 * 1024


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/api/query", methods=["POST"])
def query():
    """
    Accepts EITHER:
      - multipart "audio" file (voice path) - optional "strategy" field
      - form field "text" (typed path, no audio at all) - optional "strategy" field
    """
    request_start = time.perf_counter()
    strategy = request.form.get("strategy", "metadata")
    if strategy not in ("fixed", "semantic", "metadata"):
        return jsonify({"status": "error", "error_message": f"Invalid strategy '{strategy}'"}), 400

    typed_text = request.form.get("text", "").strip()
    has_audio = "audio" in request.files and request.files["audio"].filename != ""

    if not has_audio and not typed_text:
        return jsonify({"status": "error", "error_message": "Provide either an 'audio' file or a 'text' field"}), 400

    try:
        if typed_text and not has_audio:
            result = run_pipeline_from_text(typed_text, strategy=strategy)
        else:
            audio_file = request.files["audio"]
            ext = os.path.splitext(audio_file.filename)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                return jsonify({
                    "status": "error",
                    "error_message": f"Unsupported audio format '{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
                }), 400

            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False, dir=tempfile.gettempdir()) as tmp:
                    audio_file.save(tmp.name)
                    tmp_path = tmp.name
                if os.path.getsize(tmp_path) > MAX_AUDIO_BYTES:
                    return jsonify({"status": "error", "error_message": "Audio file too large (max 15MB)"}), 400
                result = run_pipeline(tmp_path, strategy=strategy)
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)

        result_dict = asdict(result)
        result_dict["request_latency_ms"] = round((time.perf_counter() - request_start) * 1000, 1)
        return jsonify(result_dict), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "error_message": f"Unexpected server error: {e}",
            "request_latency_ms": round((time.perf_counter() - request_start) * 1000, 1),
        }), 500


if __name__ == "__main__":
    app.run(port=5328, debug=True)