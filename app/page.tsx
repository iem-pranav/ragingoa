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

const EXAMPLE_QUESTIONS = [
  "What is biotechnology?",
  "Why is India named India?",
  "After what age should a child get a mobile phone?",
];

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
  const [textInput, setTextInput] = useState("");
  const [showDetails, setShowDetails] = useState(false);
  const [wasTextQuery, setWasTextQuery] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const progressTimerRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  async function startRecording() {
    setErrorMsg(null);
    setResult(null);
    setShowDetails(false);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => chunksRef.current.push(e.data);
      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        const formData = new FormData();
        formData.append("audio", blob, "question.webm");
        formData.append("strategy", "metadata");
        submitQuery(formData, false);
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

  function submitText() {
    const text = textInput.trim();
    if (!text) return;
    setErrorMsg(null);
    setResult(null);
    setShowDetails(false);
    const formData = new FormData();
    formData.append("text", text);
    formData.append("strategy", "metadata");
    submitQuery(formData, true);
  }

  function animateProcessingStages(isText: boolean) {
    progressTimerRef.current.forEach(clearTimeout);
    progressTimerRef.current = [];
    setActiveStageIdx(isText ? 1 : 0); // skip the "Listen" dot for typed queries - no STT happens
    let elapsed = 0;
    const totalEstimateMs = isText ? 700 : 1600;
    const stages = isText ? STAGE_WEIGHTS.slice(1) : STAGE_WEIGHTS;
    const startIdx = isText ? 1 : 0;
    
    stages.forEach((s, i) => {
      elapsed += s.share * totalEstimateMs;
      const t = setTimeout(() => setActiveStageIdx(startIdx + i + 1), elapsed);
      progressTimerRef.current.push(t);
    });
  }

  async function submitQuery(formData: FormData, isText: boolean) {
    setWasTextQuery(isText);
    setStage("processing");
    animateProcessingStages(isText);
    try {
      const res = await fetch("/api/query", { method: "POST", body: formData });
      const body: PipelineResult = await res.json();
      progressTimerRef.current.forEach(clearTimeout);
      
      if (body.status === "ok") {
        setResult(body);
        setStage("result");
      } else if (["blocked_unsafe_input", "blocked_low_confidence", "blocked_ungrounded"].includes(body.status)) {
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
    setTextInput("");
    setShowDetails(false);
  }

  const activeStages = wasTextQuery ? STAGE_WEIGHTS.slice(1) : STAGE_WEIGHTS;

  return (
    <main
      className="min-h-screen flex items-center justify-center px-4 py-12"
      style={{ background: "#0F2E24", color: "#F7F1E3" }}
    >
      <div className="w-full max-w-xl">
        <h1
          className="text-center mb-2"
          style={{ fontFamily: "var(--font-display)", fontSize: "2.25rem", fontWeight: 500, color: "#F7F1E3" }}
        >
          VaniRAG
        </h1>
        <p className="text-center mb-10" style={{ color: "#9FBBAE", fontFamily: "var(--font-body)" }}>
          Ask something in English, Hindi, Marathi, or Tamil — speak or type.
        </p>
        <div
          className="rounded-2xl p-8 relative overflow-hidden"
          style={{ background: "#163D30", border: "1px solid #24503F" }}
        >
          {/* decorative wave, evokes the coastline */}
          <svg className="absolute inset-x-0 bottom-0 opacity-10" viewBox="0 0 400 60" preserveAspectRatio="none">
            <path d="M0,30 Q50,10 100,30 T200,30 T300,30 T400,30 V60 H0 Z" fill="#C1552C" />
          </svg>
          
          {/* Details toggle - only shown once there's something to show */}
          {(stage === "result" || stage === "blocked") && result && (
            <button
              onClick={() => setShowDetails(true)}
              aria-label="Show latency and sources"
              className="absolute top-4 right-4 text-xs px-3 py-1.5 rounded-full z-10"
              style={{ background: "#24503F", color: "#9FBBAE", fontFamily: "var(--font-mono)" }}
            >
              Details
            </button>
          )}

          {stage === "idle" && (
            <div className="relative text-center py-4">
              <button
                onClick={startRecording}
                aria-label="Start recording your question"
                className="w-20 h-20 rounded-full flex items-center justify-center mx-auto transition-transform hover:scale-105 focus:outline focus:outline-2 focus:outline-offset-2"
                style={{ background: "#F2B705", outlineColor: "#F2B705" }}
              >
                <MicIcon />
              </button>
              <p className="mt-4 text-sm" style={{ color: "#9FBBAE" }}>
                Tap to ask your question
              </p>
              <div className="mt-6 flex items-center gap-2 max-w-sm mx-auto">
                <div className="flex-1 h-px" style={{ background: "#24503F" }} />
                <span className="text-xs" style={{ color: "#9FBBAE" }}>or type</span>
                <div className="flex-1 h-px" style={{ background: "#24503F" }} />
              </div>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  submitText();
                }}
                className="mt-4 flex gap-2 max-w-sm mx-auto"
              >
                <input
                  type="text"
                  value={textInput}
                  onChange={(e) => setTextInput(e.target.value)}
                  placeholder="Type your question..."
                  className="flex-1 rounded-lg px-3 py-2 text-sm outline-none"
                  style={{ background: "#0F2E24", border: "1px solid #24503F", color: "#F7F1E3", fontFamily: "var(--font-body)" }}
                />
                <button
                  type="submit"
                  disabled={!textInput.trim()}
                  className="rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-40"
                  style={{ background: "#C1552C", color: "#F7F1E3" }}
                >
                  Ask
                </button>
              </form>
              <div className="mt-6 flex flex-wrap justify-center gap-2">
                {EXAMPLE_QUESTIONS.map((ex) => (
                  <button
                    key={ex}
                    onClick={() => setTextInput(ex)}
                    className="text-xs px-3 py-1.5 rounded-full transition-colors hover:opacity-80"
                    style={{ background: "#24503F", color: "#9FBBAE", fontFamily: "var(--font-mono)" }}
                  >
                    {ex}
                  </button>
                ))}
              </div>
              <p className="mt-4 text-xs" style={{ color: "#6B8A7A" }}>
                This runs on a sampled slice of a dataset, not general knowledge — try something close to these.
              </p>
            </div>
          )}

          {stage === "recording" && (
            <div className="relative text-center py-6">
              <button
                onClick={stopRecording}
                aria-label="Stop recording"
                className="w-20 h-20 rounded-full flex items-center justify-center mx-auto animate-pulse"
                style={{ background: "#C1552C" }}
              >
                <StopIcon />
              </button>
              <p className="mt-6 text-sm" style={{ color: "#9FBBAE" }}>
                Listening — tap to stop
              </p>
            </div>
          )}

          {stage === "processing" && (
            <div className="relative py-8">
              <div className="flex justify-center gap-6">
                {activeStages.map((s) => {
                  const idx = STAGE_WEIGHTS.findIndex((w) => w.key === s.key);
                  return (
                    <div key={s.key} className="flex flex-col items-center gap-2">
                      <div
                        className="w-3 h-3 rounded-full transition-colors duration-300"
                        style={{
                          background: idx < activeStageIdx ? "#C1552C" : idx === activeStageIdx ? "#F2B705" : "#24503F",
                        }}
                      />
                      <span className="text-xs" style={{ fontFamily: "var(--font-mono)", color: "#9FBBAE" }}>
                        {s.label}
                      </span>
                    </div>
                  );
                })}
              </div>
              <p className="text-center mt-6 text-sm" style={{ color: "#9FBBAE" }}>
                Working on it…
              </p>
            </div>
          )}

          {stage === "result" && result && (
            <div className="relative">
              <div className="mb-6 pr-16">
                <p className="text-xs mb-1" style={{ fontFamily: "var(--font-mono)", color: "#9FBBAE" }}>
                  Question
                </p>
                <p className="leading-relaxed text-lg" style={{ fontFamily: "var(--font-body)", color: "#F7F1E3" }}>
                  &ldquo;{result.transcript}&rdquo;
                </p>
              </div>
              <div>
                <p className="text-xs mb-1" style={{ fontFamily: "var(--font-mono)", color: "#9FBBAE" }}>
                  Answer
                </p>
                <p className="leading-relaxed" style={{ fontFamily: "var(--font-body)" }}>
                  {result.answer}
                </p>
              </div>
              <button onClick={reset} className="mt-8 text-sm underline" style={{ color: "#F2B705" }}>
                Ask another question
              </button>
            </div>
          )}

          {stage === "blocked" && result && (
            <div className="relative">
              <p className="text-xs mb-4 pr-16" style={{ fontFamily: "var(--font-mono)", color: "#F2B705" }}>
                Not confidently grounded
              </p>
              <div className="mb-6 pr-16">
                <p className="text-xs mb-1" style={{ fontFamily: "var(--font-mono)", color: "#9FBBAE" }}>
                  Question
                </p>
                <p className="leading-relaxed text-lg" style={{ fontFamily: "var(--font-body)", color: "#F7F1E3" }}>
                  &ldquo;{result.transcript}&rdquo;
                </p>
              </div>
              <div>
                <p className="text-xs mb-1" style={{ fontFamily: "var(--font-mono)", color: "#9FBBAE" }}>
                  Answer
                </p>
                <p className="leading-relaxed" style={{ fontFamily: "var(--font-body)", color: "#F7F1E3" }}>
                  {result.answer}
                </p>
              </div>
              <button onClick={reset} className="mt-8 text-sm underline" style={{ color: "#F2B705" }}>
                Try a different question
              </button>
            </div>
          )}

          {stage === "error" && (
            <div className="relative text-center py-4">
              <p style={{ color: "#C1552C" }}>{errorMsg}</p>
              <button onClick={reset} className="mt-4 text-sm underline" style={{ color: "#F2B705" }}>
                Try again
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Details sidebar - hidden until tapped, on every screen size */}
      {showDetails && result && (
        <>
          <div
            className="fixed inset-0 z-20"
            style={{ background: "rgba(15,46,36,0.6)" }}
            onClick={() => setShowDetails(false)}
          />
          <div
            className="fixed top-0 right-0 h-full w-full max-w-sm z-30 overflow-y-auto p-6"
            style={{ background: "#163D30", borderLeft: "1px solid #24503F" }}
          >
            <div className="flex items-center justify-between mb-6">
              <h2 style={{ fontFamily: "var(--font-display)", fontSize: "1.25rem", color: "#F7F1E3" }}>
                Details
              </h2>
              <button onClick={() => setShowDetails(false)} aria-label="Close details" style={{ color: "#9FBBAE" }}>
                ✕
              </button>
            </div>
            
            <p className="text-xs mb-1" style={{ fontFamily: "var(--font-mono)", color: "#9FBBAE" }}>
              transcript
            </p>
            <p className="text-sm mb-4" style={{ fontFamily: "var(--font-body)", color: "#F7F1E3" }}>
              &ldquo;{result.transcript}&rdquo; {result.detected_language ? `· ${result.detected_language}` : ""}
            </p>
            
            <p className="text-xs mb-2" style={{ fontFamily: "var(--font-mono)", color: "#9FBBAE" }}>
              latency
            </p>
            <div className="flex flex-col gap-1 mb-6 text-xs" style={{ fontFamily: "var(--font-mono)", color: "#C1552C" }}>
              {Object.entries(result.latency_ms).map(([stage, ms]) => (
                <span key={stage}>
                  {stage}: {ms}ms
                </span>
              ))}
              {result.provider_used && <span style={{ color: "#9FBBAE" }}>provider: {result.provider_used}</span>}
            </div>

            <p className="text-xs mb-2" style={{ fontFamily: "var(--font-mono)", color: "#9FBBAE" }}>
              sources ({result.sources.length})
            </p>
            <ul className="space-y-3">
              {result.sources.map((s, i) => (
                <li key={i} className="text-sm pl-3" style={{ borderLeft: "2px solid #24503F", color: "#9FBBAE" }}>
                  <span style={{ fontFamily: "var(--font-mono)", color: "#F2B705" }}>
                    {(s.similarity * 100).toFixed(0)}%
                  </span>{" "}
                  {s.text.slice(0, 160)}…
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </main>
  );
}

function MicIcon() {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#0F2E24" strokeWidth="2">
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10v1a7 7 0 0 0 14 0v-1" />
      <line x1="12" y1="18" x2="12" y2="22" />
      <line x1="8" y1="22" x2="16" y2="22" />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="#F7F1E3">
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </svg>
  );
}