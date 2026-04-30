"use client";
import { useState, useEffect, useRef } from "react";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const C = {
  bg: "#f7f7f5",
  surface: "#ffffff",
  surfaceMuted: "#fafafa",
  border: "rgba(0,0,0,0.08)",
  borderMd: "rgba(0,0,0,0.12)",
  text: "#1a1a1a",
  textSec: "#555555",
  textMut: "#999999",
  accent: "#ff6b00",
  success: "#2f9e6e",
  running: "#d4a017",
  info: "#2f80ed",
  danger: "#e45b5b",
} as const;


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


const TOOL_LABEL: Record<string, string> = {
  plan_queries: "Planning search strategy",
  arxiv_search: "Searching arXiv",
  openalex_search: "Searching OpenAlex",
  semantic_scholar_search: "Searching Semantic Scholar",
  rank_papers: "Ranking by relevance",
  semantic_search: "Reading papers",
  extract_claims: "Extracting claims",
  verify_citations: "Verifying citation support",
  synthesize: "Writing synthesis",
};

const TOOL_COLOR: Record<string, string> = {
  plan_queries: C.info,
  arxiv_search: C.info,
  openalex_search: C.info,
  semantic_scholar_search: C.info,
  rank_papers: C.info,
  semantic_search: C.running,
  extract_claims: C.running,
  verify_citations: C.success,
  synthesize: C.success,
};


const TOOL_SEQUENCE = [
  "plan_queries",
  "arxiv_search",
  "openalex_search",
  "semantic_scholar_search",
  "rank_papers",
  "semantic_search",
  "extract_claims",
  "verify_citations",
  "synthesize",
];

function describeStep(step: TraceStep): string {
  const out = step.output as Record<string, unknown>;
  switch (step.tool) {
    case "plan_queries": {
      const n = (out?.queries as string[] | undefined)?.length;
      return n ? `Generated ${n} search queries` : "Generated search queries";
    }
    case "arxiv_search":
    case "openalex_search":
    case "semantic_scholar_search": {
      const n = out?.papers_found as number | undefined;
      const provider = out?.provider as string | undefined;
      return n !== undefined
        ? `Found ${n} paper${n !== 1 ? "s" : ""}${provider ? ` on ${provider}` : ""}`
        : "Searching…";
    }
    case "rank_papers": {
      const selected = out?.selected as number | undefined;
      const candidates = out?.candidates as number | undefined;
      return selected !== undefined && candidates !== undefined
        ? `Selected top ${selected} from ${candidates} candidates`
        : "Ranking…";
    }
    case "semantic_search": {
      const n = out?.chunks_found as number | undefined;
      return `Retrieved ${n ?? "?"} relevant passages`;
    }
    case "extract_claims": {
      const n = out?.claims_extracted as number | undefined;
      return n !== undefined ? `${n} claim${n !== 1 ? "s" : ""} extracted` : "Extracted claims";
    }
    case "verify_citations": {
      const v = out?.verified as number | undefined;
      const r = out?.rejected as number | undefined;
      return `${v ?? 0} verified · ${r ?? 0} rejected`;
    }
    case "synthesize": {
      const u = out?.citations_used as number | undefined;
      return u !== undefined ? `Written with ${u} citation${u !== 1 ? "s" : ""}` : "Synthesis complete";
    }
    default: return "";
  }
}

function nestedItems(step: TraceStep): string[] {
  const out = step.output as Record<string, unknown>;
  if (step.tool === "plan_queries") {
    return (out?.queries as string[] | undefined) ?? [];
  }
  return [];
}


type StepStatus = "done" | "running" | "failed" | "pending";

interface WorkflowItem {
  id: string;
  label: string;
  techLabel: string;
  color: string;
  steps: TraceStep[];
  status: StepStatus;
  description: string;
  nested: string[];
  totalMs: number;
}

function buildWorkflow(steps: TraceStep[], isLive: boolean): WorkflowItem[] {

  const byTool: Record<string, TraceStep[]> = {};
  for (const s of steps) {
    if (!s.tool) continue;
    (byTool[s.tool] ??= []).push(s);
  }


  let lastSeenIdx = -1;
  for (const s of steps) {
    const i = TOOL_SEQUENCE.indexOf(s.tool ?? "");
    if (i > lastSeenIdx) lastSeenIdx = i;
  }
  const nextTool = TOOL_SEQUENCE[lastSeenIdx + 1] ?? null;

  return TOOL_SEQUENCE.map(tool => {
    const toolSteps = byTool[tool] ?? [];
    const hasDone = toolSteps.some(s => s.success);
    const hasFailed = toolSteps.some(s => !s.success);
    const totalMs = toolSteps.reduce((a, s) => a + s.duration_ms, 0);

    let status: StepStatus = "pending";
    if (hasFailed) status = "failed";
    else if (hasDone) status = "done";
    else if (isLive && (tool === nextTool || (steps.length === 0 && tool === "plan_queries"))) {
      status = "running";
    }

    const last = toolSteps[toolSteps.length - 1];
    const baseDesc = last ? describeStep(last) : (status === "running" ? "Working…" : "");


    const isPerPaper = tool === "semantic_search" || tool === "extract_claims";
    const description = isPerPaper && toolSteps.length > 0
      ? `${toolSteps.length} paper${toolSteps.length !== 1 ? "s" : ""} · ${baseDesc}`
      : baseDesc;

    return {
      id: tool, label: TOOL_LABEL[tool] ?? tool,
      techLabel: tool, color: TOOL_COLOR[tool] ?? C.textMut,
      steps: toolSteps, status, description,
      nested: last ? nestedItems(last) : [],
      totalMs,
    };
  });
}


function StepDot({ status }: { status: StepStatus }) {
  if (status === "running") {
    return (
      <div style={{ width: 20, height: 20, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
        <span className="spinner-sm" />
      </div>
    );
  }
  if (status === "done") {
    return (
      <div style={{
        width: 20, height: 20, borderRadius: "50%",
        background: "#f0f0ee", border: "1.5px solid rgba(0,0,0,0.13)",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: "0.6rem", color: "#888", fontWeight: 700, flexShrink: 0,
      }}>
        ✓
      </div>
    );
  }
  if (status === "failed") {
    return (
      <div style={{
        width: 20, height: 20, borderRadius: "50%",
        background: "#fef0f0", border: `1.5px solid ${C.danger}40`,
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: "0.6rem", color: C.danger, fontWeight: 700, flexShrink: 0,
      }}>
        ✗
      </div>
    );
  }

  return (
    <div style={{
      width: 20, height: 20, borderRadius: "50%",
      border: "1.5px dashed rgba(0,0,0,0.2)",
      flexShrink: 0,
    }} />
  );
}


function TimelineItem({ item, isLast }: { item: WorkflowItem; isLast: boolean }) {
  const [open, setOpen] = useState(false);
  const canExpand = item.steps.length > 0;
  const isDone = item.status === "done";
  const isPending = item.status === "pending";
  const isRunning = item.status === "running";

  return (
    <div className="step-enter" style={{ display: "flex", gap: "0.75rem" }}>
      { }
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 2, flexShrink: 0 }}>
        <StepDot status={item.status} />
        {!isLast && (
          <div style={{
            width: 1.5, flex: 1, minHeight: 20,
            background: isDone ? "rgba(0,0,0,0.1)" : "rgba(0,0,0,0.05)",
            margin: "4px 0",
          }} />
        )}
      </div>

      { }
      <div style={{ flex: 1, paddingBottom: isLast ? 0 : "1.125rem" }}>
        { }
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
          <span style={{
            fontWeight: 600, fontSize: "0.9rem",
            color: isPending ? C.textMut : C.text,
          }}>
            {item.label}
          </span>

          {item.totalMs > 0 && (
            <span style={{ fontSize: "0.72rem", color: C.textMut, fontVariantNumeric: "tabular-nums" }}>
              {item.totalMs >= 1000
                ? `${(item.totalMs / 1000).toFixed(1)}s`
                : `${item.totalMs}ms`}
            </span>
          )}

          {canExpand && (
            <button
              onClick={() => setOpen(o => !o)}
              style={{
                marginLeft: "auto", background: "none", border: "none",
                cursor: "pointer", color: C.textMut,
                fontSize: "0.72rem", padding: "1px 6px", borderRadius: 5,
                display: "flex", alignItems: "center", gap: 3,
                transition: "color 0.1s",
              }}
            >
              Details {open ? "▲" : "▼"}
            </button>
          )}
        </div>

        { }
        {item.description && (
          <p style={{
            margin: "0.2rem 0 0",
            fontSize: "0.82rem",
            color: isPending ? C.textMut : C.textSec,
            lineHeight: 1.5,
          }}>
            {item.description}
          </p>
        )}

        { }
        {isDone && item.nested.length > 0 && (
          <ul style={{ margin: "0.4rem 0 0", paddingLeft: "1rem", listStyle: "none" }}>
            {item.nested.map((n, i) => (
              <li key={i} style={{
                position: "relative",
                fontSize: "0.8rem", color: C.textSec, lineHeight: 1.5,
                padding: "0.1rem 0",
              }}>
                <span style={{ position: "absolute", left: -12, color: C.textMut }}>·</span>
                {n}
              </li>
            ))}
          </ul>
        )}

        { }
        {isRunning && (
          <div style={{
            display: "inline-flex", alignItems: "center", gap: "0.4rem",
            marginTop: "0.4rem",
            padding: "0.25rem 0.6rem",
            background: "#fffbf0",
            border: `1px solid ${C.running}30`,
            borderRadius: 20,
            fontSize: "0.75rem", color: C.running,
          }}>
            <span className="pulse-live" style={{ width: 6, height: 6, borderRadius: "50%", background: C.running, display: "inline-block" }} />
            Working…
          </div>
        )}

        { }
        {open && (
          <div className="slide-down" style={{
            marginTop: "0.625rem",
            padding: "0.875rem",
            background: C.surfaceMuted,
            border: `1px solid ${C.border}`,
            borderRadius: 12,
            fontSize: "0.75rem",
          }}>
            {item.steps.map((step, i) => (
              <div key={i} style={{ marginBottom: i < item.steps.length - 1 ? "1rem" : 0 }}>
                {item.steps.length > 1 && (
                  <p style={{
                    margin: "0 0 0.375rem",
                    fontSize: "0.65rem", fontWeight: 700, letterSpacing: "0.06em",
                    textTransform: "uppercase", color: C.textMut,
                  }}>
                    Invocation {i + 1}
                  </p>
                )}
                {step.error && (
                  <p style={{ color: C.danger, margin: "0 0 0.375rem", fontWeight: 500 }}>
                    Error: {step.error}
                  </p>
                )}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
                  {(["input", "output"] as const).map(key => (
                    <div key={key}>
                      <p style={{
                        margin: "0 0 0.25rem",
                        fontSize: "0.63rem", fontWeight: 700,
                        textTransform: "uppercase", letterSpacing: "0.07em",
                        color: C.textMut,
                      }}>
                        {key}
                      </p>
                      <pre style={{
                        margin: 0, color: C.textSec,
                        whiteSpace: "pre-wrap", wordBreak: "break-word",
                        fontSize: "0.72rem", lineHeight: 1.55,
                      }}>
                        {JSON.stringify(step[key], null, 2)}
                      </pre>
                    </div>
                  ))}
                </div>
                <p style={{ margin: "0.5rem 0 0", color: C.textMut, fontSize: "0.68rem" }}>
                  {step.duration_ms}ms · {step.agent}
                  {" · "}{new Date(step.timestamp).toLocaleTimeString()}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}


function StatusPill({ label, elapsed }: { label: string; elapsed: number }) {
  return (
    <div style={{
      display: "inline-flex", alignItems: "center", gap: "0.5rem",
      padding: "0.4rem 0.875rem",
      background: C.surface,
      border: `1px solid ${C.border}`,
      borderRadius: 100,
      boxShadow: "0 2px 14px rgba(0,0,0,0.07)",
      marginBottom: "1.5rem",
    }}>
      <span className="spinner-sm" />
      <span style={{ fontSize: "0.82rem", fontWeight: 500, color: C.text }}>{label}</span>
      <span style={{ fontSize: "0.78rem", color: C.textMut }}>{elapsed}s</span>
    </div>
  );
}


function StatsRow({ ev }: { ev: TaskEvent }) {
  const items = [
    { label: "papers", value: ev.papers_processed, color: C.info },
    { label: "claims", value: ev.claims_extracted, color: C.running },
    { label: "citations", value: ev.citations_verified, color: C.success },
    {
      label: "duration",
      value: ev.total_duration_ms ? `${(ev.total_duration_ms / 1000).toFixed(0)}s` : "—",
      color: C.textMut,
    },
  ];
  return (
    <div style={{ display: "flex", gap: "1.25rem", flexWrap: "wrap", margin: "0.5rem 0 1.25rem" }}>
      {items.map(({ label, value, color }) => (
        <div key={label} style={{ display: "flex", alignItems: "baseline", gap: "0.3rem" }}>
          <span style={{ fontSize: "1.15rem", fontWeight: 700, color, lineHeight: 1 }}>
            {value ?? "—"}
          </span>
          <span style={{ fontSize: "0.75rem", color: C.textMut }}>{label}</span>
        </div>
      ))}
    </div>
  );
}


export default function TracePage({ params }: { params: { jobId: string } }) {
  const [status, setStatus] = useState("connecting");
  const [taskEvent, setTaskEvent] = useState<TaskEvent | null>(null);
  const [steps, setSteps] = useState<TraceStep[]>([]);
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef<number | null>(null);

  useEffect(() => {
    const { jobId } = params;

    const taskEs = new EventSource(`${API}/api/v1/stream/task/${jobId}`);
    taskEs.onmessage = (e) => {
      try {
        const ev: TaskEvent = JSON.parse(e.data);
        setTaskEvent(ev);
        setStatus(ev.event);
        if (ev.event === "started" && !startRef.current) startRef.current = Date.now();
        if (ev.event === "done" || ev.event === "failed") taskEs.close();
      } catch { }
    };
    taskEs.onerror = () => setStatus(s => s === "connecting" ? "error" : s);

    const traceEs = new EventSource(`${API}/api/v1/stream/trace/${jobId}`);
    traceEs.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data);
        if (ev.event === "step") setSteps(prev => [...prev, ev as TraceStep]);
        if (ev.event === "done" || ev.event === "failed") traceEs.close();
      } catch { }
    };

    return () => { taskEs.close(); traceEs.close(); };
  }, [params.jobId]);


  useEffect(() => {
    if (status !== "started") return;
    const t = setInterval(() => {
      if (startRef.current) setElapsed(Math.round((Date.now() - startRef.current) / 1000));
    }, 1000);
    return () => clearInterval(t);
  }, [status]);

  const isDone = status === "done";
  const isFailed = status === "failed";
  const isLive = ["connecting", "queued", "started"].includes(status);

  const workflow = buildWorkflow(steps, isLive);
  const currentItem = workflow.find(w => w.status === "running");
  const pillLabel = currentItem?.label
    ?? (status === "queued" ? "Waiting for a worker…"
      : status === "connecting" ? "Connecting…"
        : "Starting pipeline…");

  return (
    <main>
      { }
      <Link href="/" style={{
        color: C.textMut, fontSize: "0.8rem", textDecoration: "none",
        display: "inline-block", marginBottom: "1rem",
      }}>
        ← Back
      </Link>

      { }
      <h2 style={{
        margin: "0 0 0.25rem",
        fontSize: "1.35rem", fontWeight: 700, letterSpacing: "-0.015em",
        color: C.text, lineHeight: 1.25,
      }}>
        {taskEvent?.topic ?? "Research pipeline"}
      </h2>
      <p style={{ margin: "0 0 1.25rem", fontSize: "0.78rem", color: C.textMut }}>
        {isDone ? "Pipeline complete"
          : isFailed ? "Pipeline failed"
            : "Executing workflow…"}
        {" · "}job {params.jobId.slice(0, 8)}…
      </p>

      { }
      {isLive && <StatusPill label={pillLabel} elapsed={elapsed} />}

      { }
      {isFailed && (
        <div className="fade-in" style={{
          padding: "0.875rem 1rem", marginBottom: "1.25rem",
          background: "#fef5f5", border: `1px solid ${C.danger}25`, borderRadius: 12,
        }}>
          <p style={{ margin: 0, color: C.danger, fontSize: "0.875rem", fontWeight: 500 }}>
            {taskEvent?.error ?? "An unexpected error occurred."}
          </p>
        </div>
      )}

      { }
      {isDone && taskEvent && <StatsRow ev={taskEvent} />}

      { }
      {isDone && taskEvent?.review_id && (
        <div style={{ marginBottom: "1.5rem" }}>
          <Link href={`/review/${taskEvent.review_id}`} style={{
            display: "inline-flex", alignItems: "center", gap: "0.4rem",
            padding: "0.55rem 1.25rem",
            background: C.accent, color: "#fff",
            borderRadius: 9, textDecoration: "none",
            fontSize: "0.875rem", fontWeight: 600,
            boxShadow: "0 2px 10px rgba(255,107,0,0.25)",
          }}>
            View synthesis →
          </Link>
        </div>
      )}

      { }
      <div style={{
        background: C.surface,
        border: `1px solid ${C.border}`,
        borderRadius: 16,
        padding: "1.375rem 1.5rem 1rem",
        boxShadow: "0 2px 16px rgba(0,0,0,0.05)",
      }}>
        { }
        <div style={{
          display: "flex", alignItems: "center", gap: "0.5rem",
          marginBottom: "1.375rem",
          paddingBottom: "0.875rem",
          borderBottom: `1px solid ${C.border}`,
        }}>
          {isLive && <span className="spinner" />}
          {isDone && (
            <span style={{ fontSize: "0.9rem" }}>✓</span>
          )}
          <span style={{ fontWeight: 600, fontSize: "0.9rem", color: C.text }}>
            {isLive ? "Executing workflow…"
              : isDone ? "Workflow complete"
                : isFailed ? "Workflow stopped"
                  : "Pipeline"}
          </span>
          {isDone && taskEvent?.total_duration_ms && (
            <span style={{ fontSize: "0.75rem", color: C.textMut, marginLeft: 4 }}>
              {(taskEvent.total_duration_ms / 1000).toFixed(1)}s total
            </span>
          )}
        </div>

        { }
        {workflow.map((item, i) => (
          <TimelineItem
            key={item.id}
            item={item}
            isLast={i === workflow.length - 1}
          />
        ))}
      </div>
    </main>
  );
}
