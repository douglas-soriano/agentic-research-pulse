"use client";
import { useState, useEffect, useRef } from "react";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Design tokens (Slack-inspired) ─────────────────────────────────────────
const C = {
  bg:       "#1a1d21",
  surface:  "#222529",
  card:     "#27292c",
  cardHi:   "#2e3136",
  border:   "#414447",
  borderSub:"#2e3136",
  textPri:  "#d1d2d3",
  textSec:  "#9b9b9b",
  textMut:  "#616061",
  blue:     "#1d9bd1",
  blueDark: "#1264a3",
  green:    "#2bac76",
  amber:    "#e8a427",
  red:      "#e8645a",
} as const;

// ── Types ──────────────────────────────────────────────────────────────────
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

// ── Phase config ───────────────────────────────────────────────────────────
const PHASES = [
  { agents: ["search_agent"],    label: "Literature Search", color: C.blue,  tag: "search"    },
  { agents: ["extract_agent"],   label: "Claim Extraction",  color: C.amber, tag: "extract"   },
  { agents: ["synthesis_agent"], label: "Synthesis",         color: C.green, tag: "synthesis" },
] as const;

type Phase = typeof PHASES[number];

function phaseOf(agent: string): Phase {
  return PHASES.find(p => (p.agents as readonly string[]).includes(agent)) ?? PHASES[0];
}

function shortAgent(agent: string) {
  return agent.replace("_agent", "");
}

function shortDetail(input: Record<string, unknown>): string {
  if (input.query && typeof input.query === "string")
    return `"${input.query.slice(0, 48)}${input.query.length > 48 ? "…" : ""}"`;
  if (input.title && typeof input.title === "string")
    return (input.title as string).slice(0, 48) + ((input.title as string).length > 48 ? "…" : "");
  return "";
}

// ── Status badge ───────────────────────────────────────────────────────────
function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { color: string; bg: string; border: string }> = {
    connecting: { color: C.textSec, bg: C.surface,  border: C.border   },
    queued:     { color: C.amber,   bg: "#2a1f08",  border: "#5a3f0a"  },
    started:    { color: C.blue,    bg: "#0e1e2e",  border: "#1a4060"  },
    done:       { color: C.green,   bg: "#0d1f14",  border: "#1a4028"  },
    failed:     { color: C.red,     bg: "#2a1010",  border: "#5a2020"  },
    error:      { color: C.red,     bg: "#2a1010",  border: "#5a2020"  },
  };
  const s = map[status] ?? map.connecting;

  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      padding: "0.2rem 0.625rem",
      background: s.bg, color: s.color,
      borderRadius: 5,
      fontSize: "0.68rem", fontWeight: 700,
      textTransform: "uppercase", letterSpacing: "0.07em",
      border: `1px solid ${s.border}`,
    }}>
      {status === "started" && (
        <span className="pulse-live" style={{
          width: 5, height: 5, borderRadius: "50%",
          background: C.blue, display: "inline-block",
        }} />
      )}
      {status}
    </span>
  );
}

// ── Stats grid ─────────────────────────────────────────────────────────────
function StatsGrid({ event }: { event: TaskEvent }) {
  const items = [
    { label: "Papers",    value: event.papers_processed,  color: C.blue  },
    { label: "Claims",    value: event.claims_extracted,   color: C.amber },
    { label: "Citations", value: event.citations_verified, color: C.green },
    {
      label: "Duration",
      value: event.total_duration_ms
        ? `${(event.total_duration_ms / 1000).toFixed(1)}s`
        : "—",
      color: C.textSec,
    },
  ];
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "repeat(4,1fr)",
      gap: "0.625rem", marginBottom: "1.5rem",
    }}>
      {items.map(({ label, value, color }) => (
        <div key={label} style={{
          padding: "1rem 0.875rem", textAlign: "center",
          background: C.card, border: `1px solid ${C.border}`, borderRadius: 8,
        }}>
          <div style={{ fontSize: "1.5rem", fontWeight: 700, color, lineHeight: 1 }}>
            {value ?? "—"}
          </div>
          <div style={{ fontSize: "0.7rem", color: C.textMut, marginTop: 6, letterSpacing: "0.03em" }}>
            {label}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Live activity panel ────────────────────────────────────────────────────
function LivePanel({ steps, status }: { steps: TraceStep[]; status: string }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastStep  = steps[steps.length - 1];
  const phase     = lastStep ? phaseOf(lastStep.agent) : PHASES[0];
  const isRunning = status === "started";
  const isQueued  = status === "queued";

  useEffect(() => {
    if (scrollRef.current)
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [steps.length]);

  return (
    <div style={{
      background: C.surface,
      border: `1px solid ${C.border}`,
      borderRadius: 10,
      overflow: "hidden",
      marginBottom: "1.5rem",
    }}>
      {/* Panel header */}
      <div style={{
        display: "flex", alignItems: "center", gap: "0.625rem",
        padding: "0.75rem 1rem",
        borderBottom: `1px solid ${C.border}`,
        background: C.card,
      }}>
        {isRunning
          ? <span className="spinner" />
          : <span style={{
              width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
              background: isQueued ? C.amber : C.textMut,
            }} />
        }
        <span style={{ fontSize: "0.82rem", fontWeight: 600, color: C.textPri }}>
          Pipeline execution
        </span>
        {isRunning && lastStep && (
          <span style={{
            fontSize: "0.68rem", fontWeight: 700,
            color: phase.color,
            background: phase.color + "22",
            border: `1px solid ${phase.color}44`,
            padding: "1px 8px", borderRadius: 4,
          }}>
            {phase.tag}
          </span>
        )}
        <span style={{ marginLeft: "auto", fontSize: "0.72rem", color: C.textMut }}>
          {steps.length} events
        </span>
      </div>

      {/* Log rows */}
      <div ref={scrollRef} className="hide-scroll" style={{ maxHeight: 220, overflowY: "auto" }}>
        {steps.length === 0 ? (
          <div style={{ padding: "1rem", color: C.textMut, fontSize: "0.85rem" }}>
            {isQueued ? "Job queued — waiting for a worker…" : "Connecting to pipeline…"}
          </div>
        ) : (
          steps.map((step, i) => {
            const sp     = phaseOf(step.agent);
            const isLast = i === steps.length - 1;
            const detail = shortDetail(step.input);
            return (
              <div
                key={i}
                className={isLast ? "step-enter" : ""}
                style={{
                  display: "grid",
                  gridTemplateColumns: "12px 58px 1fr auto",
                  alignItems: "center",
                  gap: "0.75rem",
                  padding: "0.45rem 1rem",
                  borderBottom: i < steps.length - 1 ? `1px solid ${C.borderSub}` : "none",
                  background: isLast && isRunning ? C.cardHi : "transparent",
                  transition: "background 0.2s",
                }}
              >
                <span style={{
                  width: 7, height: 7, borderRadius: "50%",
                  background: step.success ? sp.color : C.red,
                  display: "inline-block",
                  ...(isLast && isRunning ? { animation: "pulse 1.4s ease-in-out infinite" } : {}),
                }} />
                <span style={{
                  fontSize: "0.68rem", fontWeight: 700,
                  color: sp.color,
                  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                }}>
                  {shortAgent(step.agent)}
                </span>
                <span style={{
                  fontSize: "0.82rem",
                  color: isLast && isRunning ? C.textPri : C.textSec,
                  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                  fontFamily: "ui-monospace, monospace",
                }}>
                  {step.tool}
                  {detail && (
                    <span style={{ color: C.textMut, fontSize: "0.75rem" }}> {detail}</span>
                  )}
                </span>
                <span style={{
                  fontSize: "0.7rem", color: C.textMut,
                  fontVariantNumeric: "tabular-nums", flexShrink: 0,
                }}>
                  {step.duration_ms}ms
                </span>
              </div>
            );
          })
        )}
      </div>

      {/* Progress bar */}
      {isRunning && (
        <div style={{ height: 2, background: C.borderSub }}>
          <div className="progress-slide" style={{
            height: "100%", width: "35%",
            background: `linear-gradient(90deg, transparent, ${phase.color}, transparent)`,
          }} />
        </div>
      )}
    </div>
  );
}

// ── Step row (expandable) ──────────────────────────────────────────────────
function StepRow({ step, idx }: { step: TraceStep; idx: number }) {
  const [open, setOpen] = useState(false);
  const phase  = phaseOf(step.agent);
  const detail = shortDetail(step.input);

  return (
    <div className="step-enter" style={{
      borderRadius: 6, marginBottom: "0.3rem", overflow: "hidden",
      border: `1px solid ${step.success ? C.border : "#5a2020"}`,
    }}>
      <button onClick={() => setOpen(o => !o)} style={{
        width: "100%", textAlign: "left",
        background: step.success ? C.card : "#2a1010",
        padding: "0.5rem 0.875rem",
        border: "none", cursor: "pointer",
        display: "grid",
        gridTemplateColumns: "12px 24px 58px 1fr auto auto",
        alignItems: "center",
        gap: "0.5rem",
        color: C.textPri,
      }}>
        <span style={{ color: step.success ? phase.color : C.red, fontSize: "0.65rem" }}>
          {step.success ? "●" : "✗"}
        </span>
        <span style={{ color: C.textMut, fontSize: "0.7rem", fontVariantNumeric: "tabular-nums" }}>
          {idx + 1}
        </span>
        <span style={{
          fontSize: "0.7rem", fontWeight: 700, color: phase.color,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {shortAgent(step.agent)}
        </span>
        <span style={{
          fontSize: "0.82rem", color: C.textSec,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          fontFamily: "ui-monospace, monospace",
        }}>
          {step.tool}
          {detail && <span style={{ color: C.textMut, fontSize: "0.75rem" }}> {detail}</span>}
        </span>
        <span style={{ color: C.textMut, fontSize: "0.7rem", flexShrink: 0, fontVariantNumeric: "tabular-nums" }}>
          {step.duration_ms}ms
        </span>
        <span style={{ color: C.textMut, fontSize: "0.65rem", flexShrink: 0 }}>
          {open ? "▲" : "▼"}
        </span>
      </button>

      {open && (
        <div style={{
          padding: "0.875rem",
          background: C.surface,
          borderTop: `1px solid ${C.border}`,
          fontSize: "0.78rem",
        }}>
          {step.error && (
            <p style={{ color: C.red, margin: "0 0 0.625rem", fontWeight: 500 }}>
              Error: {step.error}
            </p>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
            {(["input", "output"] as const).map(key => (
              <div key={key}>
                <p style={{
                  color: C.textMut, margin: "0 0 0.375rem",
                  textTransform: "uppercase", fontSize: "0.65rem",
                  letterSpacing: "0.07em", fontWeight: 700,
                }}>
                  {key}
                </p>
                <pre style={{
                  margin: 0, color: C.textSec,
                  whiteSpace: "pre-wrap", wordBreak: "break-word",
                  fontSize: "0.75rem", lineHeight: 1.6,
                }}>
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

// ── Phase accordion ────────────────────────────────────────────────────────
function PhaseAccordion({ phase, steps }: { phase: Phase; steps: TraceStep[] }) {
  const [open, setOpen] = useState(false);
  const phaseSteps = steps.filter(s => (phase.agents as readonly string[]).includes(s.agent));
  if (!phaseSteps.length) return null;

  const ok      = phaseSteps.filter(s => s.success).length;
  const failed  = phaseSteps.length - ok;
  const totalMs = phaseSteps.reduce((a, s) => a + s.duration_ms, 0);

  return (
    <div style={{
      marginBottom: "0.5rem",
      border: `1px solid ${C.border}`,
      borderRadius: 8, overflow: "hidden",
    }}>
      <button onClick={() => setOpen(o => !o)} style={{
        width: "100%", textAlign: "left",
        background: C.card,
        padding: "0.75rem 1rem",
        border: "none", cursor: "pointer",
        display: "flex", alignItems: "center", gap: "0.75rem",
        color: C.textPri,
      }}>
        <span style={{
          width: 8, height: 8, borderRadius: "50%",
          background: phase.color, flexShrink: 0,
        }} />
        <span style={{ fontWeight: 600, fontSize: "0.875rem" }}>{phase.label}</span>
        <span style={{ color: C.textMut, fontSize: "0.75rem" }}>
          {phaseSteps.length} steps · {(totalMs / 1000).toFixed(1)}s
        </span>
        {failed > 0 && (
          <span style={{ color: C.red, fontSize: "0.75rem" }}>{failed} failed</span>
        )}
        <span style={{ color: C.textMut, fontSize: "0.7rem", marginLeft: "auto" }}>
          {open ? "▲" : "▼"}
        </span>
      </button>

      {open && (
        <div style={{ background: C.surface, padding: "0.5rem" }}>
          {phaseSteps.map((step, i) => <StepRow key={i} step={step} idx={i} />)}
        </div>
      )}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────
export default function TracePage({ params }: { params: { jobId: string } }) {
  const [status,    setStatus]    = useState("connecting");
  const [taskEvent, setTaskEvent] = useState<TaskEvent | null>(null);
  const [steps,     setSteps]     = useState<TraceStep[]>([]);

  useEffect(() => {
    const { jobId } = params;

    const taskEs = new EventSource(`${API}/api/v1/stream/task/${jobId}`);
    taskEs.onmessage = (e) => {
      try {
        const ev: TaskEvent = JSON.parse(e.data);
        setTaskEvent(ev);
        setStatus(ev.event);
        if (ev.event === "done" || ev.event === "failed") taskEs.close();
      } catch { /* ignore */ }
    };
    taskEs.onerror = () => setStatus("error");

    const traceEs = new EventSource(`${API}/api/v1/stream/trace/${jobId}`);
    traceEs.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data);
        if (ev.event === "step") setSteps(prev => [...prev, ev as TraceStep]);
        if (ev.event === "done" || ev.event === "failed") traceEs.close();
      } catch { /* ignore */ }
    };

    return () => { taskEs.close(); traceEs.close(); };
  }, [params.jobId]);

  const isDone   = status === "done";
  const isFailed = status === "failed";
  const isLive   = ["connecting", "queued", "started"].includes(status);

  return (
    <main>
      {/* Page header */}
      <div style={{ marginBottom: "1.5rem" }}>
        <Link href="/" style={{ color: C.textMut, fontSize: "0.8rem", textDecoration: "none" }}>
          ← Back
        </Link>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginTop: "0.5rem", flexWrap: "wrap" }}>
          <h2 style={{ margin: 0, fontSize: "1.15rem", color: C.textPri, fontWeight: 700, letterSpacing: "-0.01em" }}>
            {taskEvent?.topic ?? params.jobId}
          </h2>
          <StatusBadge status={status} />
        </div>
        <p style={{ color: C.textMut, fontSize: "0.73rem", margin: "0.3rem 0 0" }}>
          {steps.length} steps · job {params.jobId.slice(0, 8)}…
        </p>
      </div>

      {/* Live panel */}
      {isLive && <LivePanel steps={steps} status={status} />}

      {/* Completion stats */}
      {isDone && taskEvent && (
        <>
          <StatsGrid event={taskEvent} />
          {taskEvent.review_id && (
            <div style={{ marginBottom: "1.5rem" }}>
              <Link href={`/review/${taskEvent.review_id}`} style={{
                display: "inline-flex", alignItems: "center", gap: "0.5rem",
                padding: "0.55rem 1.125rem",
                background: C.blueDark,
                color: "#fff",
                borderRadius: 6,
                textDecoration: "none",
                fontSize: "0.875rem", fontWeight: 600,
              }}>
                View completed review →
              </Link>
            </div>
          )}
        </>
      )}

      {/* Error banner */}
      {isFailed && (
        <div style={{
          padding: "0.875rem 1rem", marginBottom: "1.5rem",
          background: "#2a1010", border: `1px solid ${C.red}50`, borderRadius: 8,
        }}>
          <p style={{ color: C.red, margin: 0, fontSize: "0.875rem", fontWeight: 500 }}>
            Pipeline failed: {taskEvent?.error ?? "unknown error"}
          </p>
        </div>
      )}

      {/* Step breakdown — only shown after completion */}
      {(isDone || isFailed) && steps.length > 0 && (
        <div>
          <div style={{
            display: "flex", alignItems: "center", gap: "0.5rem",
            marginBottom: "0.625rem",
          }}>
            <span style={{
              fontSize: "0.7rem", color: C.textSec,
              textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 700,
            }}>
              Agent steps ({steps.length})
            </span>
          </div>
          {PHASES.map(phase => (
            <PhaseAccordion key={phase.label} phase={phase} steps={steps} />
          ))}
        </div>
      )}
    </main>
  );
}
