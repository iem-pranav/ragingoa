"use client";

import { useRef, useState } from "react";

type Stage = "idle" | "recording" | "processing" | "result" | "blocked" | "error";

type PipelineResult = {
  status: string;
  answer: string | null;
  transcript: string | null;
  detected_language: string | null;
  sources: { text: string; similarity: number; metadata: Record<string, unknown> }[];
  provider_used: string | null;
  error_message: string | null;
  latency_ms: Record<string, number>;
  request_latency_ms: number;
  strategy_used: string;
};

// Rough expected share of total time per stage, from our own benchmark medians -
// used only to animate the console while we wait; replaced by real numbers the
// moment the actual response lands. Not a promise, just a believable rhythm.
const STAGE_WEIGHTS: { key: string; label: string; share: number }[] = [
  { key: "stt", label: "Listen", share: 0.4 },
  { key: "retrieval", label: "Search", share: 0.35 },
  { key: "generation", label: "Answer", share: 0.25 },
];

export default function Home() {
  const [stage, setStage] = useState<Stage>("idle");
  const [activeStageIdx, setActiveStageIdx] = useState(0);
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const progressTimerRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  async function startRecording() {
    setErrorMsg(null);
    setResult(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => chunksRef.current.push(e.data);
      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        submitRecording();
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setStage("recording");
    } catch {
      setErrorMsg("Couldn't access your microphone. Check your browser's permission settings.");
      setStage("error");
    }
  }

  function stopRecording() {
    mediaRecorderRef.current?.stop();
  }

  function animateProcessingStages() {
    progressTimerRef.current.forEach(clearTimeout);
    progressTimerRef.current = [];
    setActiveStageIdx(0);
    let elapsed = 0;
    const totalEstimateMs = 1600; // close to our own measured p50
    STAGE_WEIGHTS.forEach((s, i) => {
      elapsed += s.share * totalEstimateMs;
      const t = setTimeout(() => setActiveStageIdx(i + 1), elapsed);
      progressTimerRef.current.push(t);
    });
  }

  async function submitRecording() {
    setStage("processing");
    animateProcessingStages();

    const blob = new Blob(chunksRef.current, { type: "audio/webm" });
    const formData = new FormData();
    formData.append("audio", blob, "question.webm");
    formData.append("strategy", "metadata");

    try {
      const res = await fetch("/api/query", { method: "POST", body: formData });
      const body: PipelineResult = await res.json();
      progressTimerRef.current.forEach(clearTimeout);

      if (body.status === "ok") {
        setResult(body);
        setStage("result");
      } else if (body.status === "blocked_unsafe_input" || body.status === "blocked_low_confidence" || body.status === "blocked_ungrounded") {
        setResult(body);
        setStage("blocked");
      } else {
        setErrorMsg(body.error_message ?? "Something went wrong processing that.");
        setStage("error");
      }
    } catch {
      progressTimerRef.current.forEach(clearTimeout);
      setErrorMsg("Couldn't reach the server. Check your connection and try again.");
      setStage("error");
    }
  }

  function reset() {
    setStage("idle");
    setResult(null);
    setErrorMsg(null);
  }

  return (
    <main className="min-h-screen flex items-center justify-center px-4 py-12"
          style={{ background: "#14152B", color: "#F5F3EC" }}>
      <div className="w-full max-w-xl">

        <h1 className="text-center mb-2"
            style={{ fontFamily: "var(--font-display)", fontSize: "2.25rem", fontWeight: 500, color: "#F5F3EC" }}>
          RAGInGoa
        </h1>
        <p className="text-center mb-10" style={{ color: "#9A9BC0", fontFamily: "var(--font-body)" }}>
          Ask something in English, Hindi, Marathi, or Tamil — out loud.
        </p>

        <div className="rounded-2xl p-8 relative overflow-hidden"
             style={{ background: "#1D1F3D", border: "1px solid #2A2C52" }}>

          <svg className="absolute inset-x-0 bottom-0 opacity-10" viewBox="0 0 400 60" preserveAspectRatio="none">
            <path d="M0,30 Q50,10 100,30 T200,30 T300,30 T400,30 V60 H0 Z" fill="#3FCFB4" />
          </svg>

          {stage === "idle" && (
            <div className="relative text-center py-6">
              <button
                onClick={startRecording}
                aria-label="Start recording your question"
                className="w-20 h-20 rounded-full flex items-center justify-center mx-auto transition-transform hover:scale-105 focus:outline focus:outline-2 focus:outline-offset-2"
                style={{ background: "#F2A93B", outlineColor: "#F2A93B" }}
              >
                <MicIcon />
              </button>
              <p className="mt-6 text-sm" style={{ color: "#9A9BC0" }}>Tap to ask your question</p>
            </div>
          )}

          {stage === "recording" && (
            <div className="relative text-center py-6">
              <button
                onClick={stopRecording}
                aria-label="Stop recording"
                className="w-20 h-20 rounded-full flex items-center justify-center mx-auto animate-pulse"
                style={{ background: "#E85D5D" }}
              >
                <StopIcon />
              </button>
              <p className="mt-6 text-sm" style={{ color: "#9A9BC0" }}>Listening — tap to stop</p>
            </div>
          )}

          {stage === "processing" && (
            <div className="relative py-8">
              <div className="flex justify-center gap-6">
                {STAGE_WEIGHTS.map((s, i) => (
                  <div key={s.key} className="flex flex-col items-center gap-2">
                    <div
                      className="w-3 h-3 rounded-full transition-colors duration-300"
                      style={{ background: i < activeStageIdx ? "#3FCFB4" : i === activeStageIdx ? "#F2A93B" : "#2A2C52" }}
                    />
                    <span className="text-xs" style={{ fontFamily: "var(--font-mono)", color: "#9A9BC0" }}>
                      {s.label}
                    </span>
                  </div>
                ))}
              </div>
              <p className="text-center mt-6 text-sm" style={{ color: "#9A9BC0" }}>Working on it…</p>
            </div>
          )}

          {stage === "result" && result && (
            <div className="relative">
              <p className="text-xs mb-1" style={{ fontFamily: "var(--font-mono)", color: "#9A9BC0" }}>
                &ldquo;{result.transcript}&rdquo; · {result.detected_language}
              </p>
              <p className="mt-3 leading-relaxed" style={{ fontFamily: "var(--font-body)" }}>
                {result.answer}
              </p>

              <div className="mt-6 flex gap-4 text-xs" style={{ fontFamily: "var(--font-mono)", color: "#3FCFB4" }}>
                <span>stt {result.latency_ms.stt}ms</span>
                <span>search {result.latency_ms.retrieval}ms</span>
                <span>answer {result.latency_ms.generation}ms</span>
                <span style={{ color: "#9A9BC0" }}>· {result.provider_used}</span>
              </div>

              <details className="mt-5">
                <summary className="text-sm cursor-pointer" style={{ color: "#9A9BC0" }}>
                  Sources ({result.sources.length})
                </summary>
                <ul className="mt-3 space-y-3">
                  {result.sources.map((s, i) => (
                    <li key={i} className="text-sm pl-3" style={{ borderLeft: "2px solid #2A2C52", color: "#9A9BC0" }}>
                      <span style={{ fontFamily: "var(--font-mono)", color: "#3FCFB4" }}>
                        {(s.similarity * 100).toFixed(0)}%
                      </span>{" "}
                      {s.text.slice(0, 140)}…
                    </li>
                  ))}
                </ul>
              </details>

              <button onClick={reset} className="mt-6 text-sm underline" style={{ color: "#F2A93B" }}>
                Ask another question
              </button>
            </div>
          )}

          {stage === "blocked" && result && (
            <div className="relative">
              <p className="text-xs mb-3" style={{ fontFamily: "var(--font-mono)", color: "#F2A93B" }}>
                Not confidently grounded
              </p>
              <p className="leading-relaxed" style={{ fontFamily: "var(--font-body)", color: "#F5F3EC" }}>
                {result.answer}
              </p>
              <button onClick={reset} className="mt-6 text-sm underline" style={{ color: "#F2A93B" }}>
                Try a different question
              </button>
            </div>
          )}

          {stage === "error" && (
            <div className="relative text-center py-4">
              <p style={{ color: "#E85D5D" }}>{errorMsg}</p>
              <button onClick={reset} className="mt-4 text-sm underline" style={{ color: "#F2A93B" }}>
                Try again
              </button>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}

function MicIcon() {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#14152B" strokeWidth="2">
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10v1a7 7 0 0 0 14 0v-1" />
      <line x1="12" y1="18" x2="12" y2="22" />
      <line x1="8" y1="22" x2="16" y2="22" />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="#F5F3EC">
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </svg>
  );
}