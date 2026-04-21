"use client";
import { useState, useEffect, useRef } from "react";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ---- Types ----------------------------------------------------------------

interface TaskEvent {
  event: "queued" | "started" | "done" | "failed";
  job_id: string;
  topic?: string;
  review_id?: string;
  error?: string;
  papers_processed?: number;
  claims_extracted?: number;
  citations_verified?: number;
  citations_rejected?: number;
  total_duration_ms?: number;
  ts: string;
}

interface TraceStep {
  event: "step";
  job_id: string;
  agent: string;
  tool: string | null;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  duration_ms: number;
  success: boolean;
  error: string | null;
  timestamp: string;
}

// ---- Helpers ---------------------------------------------------------------

const statusColor: Record<string, string> = {
  queued: "#f6e05e",
  started: "#63b3ed",
  done: "#68d391",
  failed: "#fc8181",
};

function StepRow({ step, idx }: { step: TraceStep; idx: number }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{
      border: `1px solid ${step.success ? "#2d3748" : "#742a2a"}`,
      borderRadius: 6,
      marginBottom: "0.5rem",
      overflow: "hidden",
    }}>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          width: "100%", textAlign: "left",
          background: step.success ? "#1a202c" : "#2d1515",
          padding: "0.6rem 1rem", border: "none", color: "#e2e8f0",
          cursor: "pointer", display: "flex",
          justifyContent: "space-between", alignItems: "center",
          fontSize: "0.85rem",
        }}
      >
        <span>
          <span style={{ color: "#63b3ed", marginRight: 8 }}>#{idx + 1}</span>
          <span style={{ color: "#9ae6b4", marginRight: 6 }}>{step.agent}</span>
          {step.tool && <span style={{ color: "#fbd38d" }}>→ {step.tool}</span>}
          {!step.success && <span style={{ color: "#fc8181", marginLeft: 8 }}>✗ FAILED</span>}
        </span>
        <span style={{ color: "#718096" }}>{step.duration_ms}ms {open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div style={{ padding: "0.75rem 1rem", background: "#111827", fontSize: "0.8rem" }}>
          {step.error && <p style={{ color: "#fc8181", margin: "0 0 0.5rem" }}>Error: {step.error}</p>}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
            {(["input", "output"] as const).map((key) => (
              <div key={key}>
                <p style={{ color: "#718096", margin: "0 0 0.25rem", textTransform: "uppercase", fontSize: "0.7rem" }}>{key}</p>
                <pre style={{ margin: 0, color: "#a0aec0", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                  {JSON.stringify(step[key], null, 2)}
                </pre>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---- Page ------------------------------------------------------------------

export default function TracePage({ params }: { params: { jobId: string } }) {
  const [status, setStatus] = useState<string>("connecting");
  const [taskEvent, setTaskEvent] = useState<TaskEvent | null>(null);
  const [steps, setSteps] = useState<TraceStep[]>([]);
  const taskSseRef = useRef<EventSource | null>(null);
  const traceSseRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const { jobId } = params;

    // ---- Task lifecycle stream ----
    const taskEs = new EventSource(`${API}/api/v1/stream/task/${jobId}`);
    taskSseRef.current = taskEs;

    taskEs.onmessage = (e) => {
      try {
        const ev: TaskEvent = JSON.parse(e.data);
        setTaskEvent(ev);
        setStatus(ev.event);
        if (ev.event === "done" || ev.event === "failed") {
          taskEs.close();
        }
      } catch { /* ignore parse errors */ }
    };
    taskEs.onerror = () => setStatus("error");

    // ---- Trace step stream ----
    const traceEs = new EventSource(`${API}/api/v1/stream/trace/${jobId}`);
    traceSseRef.current = traceEs;

    traceEs.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data);
        if (ev.event === "step") {
          setSteps((prev) => [...prev, ev as TraceStep]);
        }
        if (ev.event === "done" || ev.event === "failed") {
          traceEs.close();
        }
      } catch { /* ignore */ }
    };

    return () => {
      taskEs.close();
      traceEs.close();
    };
  }, [params.jobId]);

  const color = statusColor[status] ?? "#a0aec0";

  return (
    <main>
      <div style={{ marginBottom: "1.5rem" }}>
        <Link href="/" style={{ color: "#63b3ed", fontSize: "0.875rem" }}>← Back</Link>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginTop: "0.5rem" }}>
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>
            {taskEvent?.topic ?? params.jobId}
          </h2>
          <span style={{
            padding: "0.2rem 0.6rem", background: "#2d3748", borderRadius: 4,
            color, fontSize: "0.75rem", fontWeight: 600, textTransform: "uppercase",
          }}>
            {status}
          </span>
          {status === "started" && (
            <span style={{ color: "#718096", fontSize: "0.75rem" }}>
              (live — steps arrive in real time)
            </span>
          )}
        </div>
        <p style={{ color: "#718096", fontSize: "0.8rem", margin: "0.25rem 0 0" }}>
          Job {params.jobId} · {steps.length} steps so far
        </p>
      </div>

      {/* Stats — shown once done */}
      {taskEvent?.event === "done" && (
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(4, 1fr)",
          gap: "0.75rem", marginBottom: "1.5rem",
        }}>
          {([
            ["Papers", taskEvent.papers_processed, "#63b3ed"],
            ["Claims", taskEvent.claims_extracted, "#fbd38d"],
            ["Verified", taskEvent.citations_verified, "#68d391"],
            ["Rejected", taskEvent.citations_rejected, "#fc8181"],
          ] as [string, number | undefined, string][]).map(([label, value, c]) => (
            <div key={label} style={{
              padding: "0.75rem", background: "#1a202c",
              border: "1px solid #2d3748", borderRadius: 8, textAlign: "center",
            }}>
              <div style={{ fontSize: "1.5rem", fontWeight: 700, color: c }}>{value ?? "—"}</div>
              <div style={{ fontSize: "0.75rem", color: "#718096" }}>{label}</div>
            </div>
          ))}
        </div>
      )}

      {taskEvent?.event === "failed" && (
        <div style={{ padding: "0.75rem 1rem", background: "#2d1515", border: "1px solid #742a2a", borderRadius: 6, marginBottom: "1rem" }}>
          <p style={{ color: "#fc8181", margin: 0 }}>Pipeline failed: {taskEvent.error}</p>
        </div>
      )}

      {taskEvent?.event === "done" && taskEvent.review_id && (
        <div style={{ marginBottom: "1rem" }}>
          <Link
            href={`/review/${taskEvent.review_id}`}
            style={{ color: "#68d391", fontSize: "0.9rem" }}
          >
            View completed review →
          </Link>
        </div>
      )}

      <h3 style={{ fontSize: "0.9rem", color: "#a0aec0", marginBottom: "0.75rem" }}>
        Agent Steps
        {status === "started" && <span style={{ color: "#63b3ed", marginLeft: 8, fontSize: "0.75rem" }}>● live</span>}
      </h3>
      {steps.length === 0 && (
        <p style={{ color: "#718096" }}>
          {["connecting", "queued"].includes(status) ? "Waiting for pipeline to start…" : "No steps yet."}
        </p>
      )}
      {steps.map((s, i) => <StepRow key={i} step={s} idx={i} />)}
    </main>
  );
}
