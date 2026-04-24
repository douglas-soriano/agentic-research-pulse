"use client";
import { useState, useEffect, useRef, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const C = {
  bg:          "#f7f7f5",
  surface:     "#ffffff",
  surfaceMuted:"#fafafa",
  border:      "rgba(0,0,0,0.08)",
  borderMd:    "rgba(0,0,0,0.13)",
  text:        "#1a1a1a",
  textSec:     "#555555",
  textMut:     "#999999",
  accent:      "#ff6b00",
  success:     "#2f9e6e",
  running:     "#d4a017",
  info:        "#2f80ed",
  danger:      "#e45b5b",
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

interface CitationEntry {
  paper_id: string; arxiv_id: string;
  title: string;    authors: string[];
  chunk_id: string;
}

interface CitedPaper {
  paper_id: string; arxiv_id: string;
  title: string;    authors: string[];
  chunk_ids: string[];
}

interface Review {
  id: string; topic_id: string; topic_name: string;
  synthesis: string;
  citations: Record<string, CitationEntry>;
  cited_papers: CitedPaper[];
  papers_processed: number; claims_extracted: number;
  citations_verified: number; citations_rejected: number;
  version: number; updated_at: string;
}

// ── Pipeline labels ────────────────────────────────────────────────────────
const TOOL_LABEL: Record<string, string> = {
  plan_queries:          "Planning search strategy",
  parallel_arxiv_search: "Searching arXiv",
  semantic_search:       "Reading papers",
  extract_claims:        "Extracting claims",
  verify_citations:      "Verifying citation support",
  synthesize:            "Writing synthesis",
};

const TOOL_COLOR: Record<string, string> = {
  plan_queries:          C.info,
  parallel_arxiv_search: C.info,
  semantic_search:       C.running,
  extract_claims:        C.running,
  verify_citations:      C.success,
  synthesize:            C.success,
};

const TOOL_SEQUENCE = [
  "plan_queries", "parallel_arxiv_search",
  "semantic_search", "extract_claims",
  "verify_citations", "synthesize",
];

/** Pretty labels for provider names stored in trace steps */
const PROVIDER_DISPLAY: Record<string, string> = {
  gemini: "Gemini",
  chatgpt: "ChatGPT",
  openai: "ChatGPT",
  local: "Local (Ollama)",
};

function displayProviderName(name: string): string {
  const k = name.toLowerCase();
  return PROVIDER_DISPLAY[k] ?? name;
}

function describeStep(step: TraceStep): string {
  const out = step.output as Record<string, unknown>;
  switch (step.tool) {
    case "plan_queries": {
      const n = (out?.queries as string[] | undefined)?.length;
      return n ? `Generated ${n} search queries` : "Generated search queries";
    }
    case "parallel_arxiv_search": {
      const n = out?.unique_papers as number | undefined;
      return n !== undefined ? `Found ${n} candidate papers` : "Searched arXiv";
    }
    case "semantic_search":   return `Retrieved ${(out?.chunks_found as number) ?? "?"} passages`;
    case "extract_claims":    return `${(out?.claims_extracted as number) ?? "?"} claims extracted`;
    case "verify_citations":  return `${(out?.verified as number) ?? 0} verified · ${(out?.rejected as number) ?? 0} rejected`;
    case "synthesize":        return `Written with ${(out?.citations_used as number) ?? "?"} citations`;
    default: return "";
  }
}

function nestedItems(step: TraceStep): string[] {
  if (step.tool === "plan_queries") {
    return (step.output as Record<string, unknown>)?.queries as string[] ?? [];
  }
  return [];
}

type StepStatus = "done" | "running" | "failed" | "pending";

/** When `phase_tool` is absent on older traces, infer the pipeline step from the agent. */
const AGENT_TO_PHASE_TOOL: Record<string, string> = {
  search_agent: "plan_queries",
  extract_agent: "extract_claims",
  synthesis_agent: "synthesize",
};

function phaseToolForProviderStep(s: TraceStep): string {
  const pt = s.input?.phase_tool;
  if (typeof pt === "string" && pt.length > 0) return pt;
  return AGENT_TO_PHASE_TOOL[s.agent] ?? "";
}

interface ProviderFallbackSummary {
  from: string;
  to: string;
  count: number;
}

/** One line per distinct from→to per phase; count merges repeated switches (e.g. per-paper LLM calls). */
function providerFallbacksForPhase(
  allSteps: TraceStep[],
  toolId: string,
): ProviderFallbackSummary[] {
  const relevant = allSteps.filter(
    s => s.tool === "provider_switch" && phaseToolForProviderStep(s) === toolId,
  );
  const byPair = new Map<string, ProviderFallbackSummary>();
  for (const s of relevant) {
    const from = String(s.input?.from ?? "");
    const to = String(s.output?.to ?? "");
    const key = `${from}\0${to}`;
    const cur = byPair.get(key);
    if (cur) cur.count += 1;
    else byPair.set(key, { from, to, count: 1 });
  }
  return [...byPair.values()];
}

interface WorkflowItem {
  id: string; label: string; techLabel: string; color: string;
  steps: TraceStep[]; status: StepStatus;
  description: string; nested: string[]; totalMs: number;
  providerFallbacks: ProviderFallbackSummary[];
}

function buildWorkflow(steps: TraceStep[], isLive: boolean): WorkflowItem[] {
  const byTool: Record<string, TraceStep[]> = {};
  for (const s of steps) {
    if (!s.tool) continue;
    (byTool[s.tool] ??= []).push(s);
  }

  // Index of the latest tool seen in steps
  let lastIdx = -1;
  for (const s of steps) {
    const i = TOOL_SEQUENCE.indexOf(s.tool ?? "");
    if (i > lastIdx) lastIdx = i;
  }

  // Is the frontmost tool still accumulating (has steps, but no later tool has started yet)?
  // If so, don't mark the *next* tool as "running" — it hasn't started yet.
  const frontToolIsAccumulating =
    lastIdx >= 0 &&
    isLive &&
    (byTool[TOOL_SEQUENCE[lastIdx]] ?? []).some(s => s.success) &&
    !steps.some(s => TOOL_SEQUENCE.indexOf(s.tool ?? "") > lastIdx);

  return TOOL_SEQUENCE.map((tool, toolIdx) => {
    const ts       = byTool[tool] ?? [];
    const hasDone  = ts.some(s => s.success);
    const hasFail  = ts.some(s => !s.success);
    const totalMs  = ts.reduce((a, s) => a + s.duration_ms, 0);

    // A later stage has already produced steps → this one is truly finished
    const hasLaterStarted = steps.some(
      s => TOOL_SEQUENCE.indexOf(s.tool ?? "") > toolIdx
    );

    let status: StepStatus = "pending";
    if (hasFail) {
      status = "failed";
    } else if (hasDone && (!isLive || hasLaterStarted)) {
      // Done: pipeline finished, or a confirmed-later step proves we moved on
      status = "done";
    } else if (hasDone && isLive && !hasLaterStarted) {
      // Still live, no later step yet → still accumulating (per-paper tools)
      status = "running";
    } else if (
      isLive &&
      !frontToolIsAccumulating &&        // ← key fix: don't pre-run next while front is busy
      (tool === TOOL_SEQUENCE[lastIdx + 1] || (steps.length === 0 && tool === "plan_queries"))
    ) {
      status = "running";
    }

    const last      = ts[ts.length - 1];
    const baseDesc  = last ? describeStep(last) : (status === "running" ? "Working…" : "");
    const isPerPaper = tool === "semantic_search" || tool === "extract_claims";
    const description = isPerPaper && ts.length > 0
      ? `${ts.length} paper${ts.length !== 1 ? "s" : ""} · ${baseDesc}` : baseDesc;

    return {
      id: tool, label: TOOL_LABEL[tool] ?? tool,
      techLabel: tool, color: TOOL_COLOR[tool] ?? C.textMut,
      steps: ts, status, description,
      nested: last ? nestedItems(last) : [],
      totalMs,
      providerFallbacks: providerFallbacksForPhase(steps, tool),
    };
  });
}

// ── Step dot ───────────────────────────────────────────────────────────────
function StepDot({ status }: { status: StepStatus }) {
  if (status === "running") return (
    <div style={{ width: 20, height: 20, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
      <span className="spinner-sm" />
    </div>
  );
  const base: React.CSSProperties = {
    width: 20, height: 20, borderRadius: "50%", flexShrink: 0,
    display: "flex", alignItems: "center", justifyContent: "center",
    fontSize: "0.6rem", fontWeight: 700,
  };
  if (status === "done")   return <div style={{ ...base, background: "#f0f0ee", border: "1.5px solid rgba(0,0,0,0.13)", color: "#888" }}>✓</div>;
  if (status === "failed") return <div style={{ ...base, background: "#fef0f0", border: `1.5px solid ${C.danger}40`, color: C.danger }}>✗</div>;
  return <div style={{ ...base, border: "1.5px dashed rgba(0,0,0,0.2)" }} />;
}

// ── Workflow timeline item ─────────────────────────────────────────────────
function TimelineItem({ item, isLast }: { item: WorkflowItem; isLast: boolean }) {
  const [open, setOpen] = useState(false);
  const isPending = item.status === "pending";
  const isRunning = item.status === "running";
  const isDone    = item.status === "done";

  return (
    <div className="step-enter" style={{ display: "flex", gap: "0.625rem" }}>
      {/* Dot + line */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 2, flexShrink: 0 }}>
        <StepDot status={item.status} />
        {!isLast && <div style={{ width: 1.5, flex: 1, minHeight: 18, background: isDone ? "rgba(0,0,0,0.1)" : "rgba(0,0,0,0.05)", margin: "3px 0" }} />}
      </div>

      {/* Content */}
      <div style={{ flex: 1, paddingBottom: isLast ? 0 : "1rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", flexWrap: "wrap" }}>
          <span style={{ fontWeight: 600, fontSize: "0.875rem", color: isPending ? C.textMut : C.text }}>
            {item.label}
          </span>
          {item.totalMs > 0 && (
            <span style={{ fontSize: "0.7rem", color: C.textMut }}>
              {item.totalMs >= 1000 ? `${(item.totalMs / 1000).toFixed(1)}s` : `${item.totalMs}ms`}
            </span>
          )}
          {item.steps.length > 0 && (
            <button onClick={() => setOpen(o => !o)} style={{
              marginLeft: "auto", background: "none", border: "none", cursor: "pointer",
              color: C.textMut, fontSize: "0.7rem", padding: "1px 5px", borderRadius: 4,
            }}>
              Details {open ? "▲" : "▼"}
            </button>
          )}
        </div>

        {item.description && (
          <p style={{ margin: "0.15rem 0 0", fontSize: "0.8rem", color: isPending ? C.textMut : C.textSec, lineHeight: 1.4 }}>
            {item.description}
          </p>
        )}

        {item.providerFallbacks.length > 0 && (
          <ul style={{ margin: "0.35rem 0 0", padding: "0 0 0 0.75rem", listStyle: "none" }}>
            {item.providerFallbacks.map((fb, i) => (
              <li
                key={`${fb.from}-${fb.to}-${i}`}
                style={{
                  position: "relative",
                  fontSize: "0.76rem",
                  color: C.textSec,
                  lineHeight: 1.45,
                  fontStyle: "italic",
                  padding: "0.06rem 0",
                }}
              >
                <span style={{ position: "absolute", left: -10, color: C.textMut, fontStyle: "normal" }}>→</span>
                <span style={{ fontStyle: "normal", fontWeight: 600 }}>{displayProviderName(fb.from)}</span>
                {" "}was unavailable — continued with{" "}
                <span style={{ fontStyle: "normal", fontWeight: 600 }}>{displayProviderName(fb.to)}</span>
                {fb.count > 1 ? ` (${fb.count} LLM calls in this step).` : "."}
              </li>
            ))}
          </ul>
        )}

        {/* Generated queries as sub-bullets */}
        {isDone && item.nested.length > 0 && (
          <ul style={{ margin: "0.35rem 0 0", padding: "0 0 0 0.875rem", listStyle: "none" }}>
            {item.nested.map((n, i) => (
              <li key={i} style={{ position: "relative", fontSize: "0.77rem", color: C.textSec, lineHeight: 1.5, padding: "0.05rem 0" }}>
                <span style={{ position: "absolute", left: -12, color: C.textMut }}>·</span>{n}
              </li>
            ))}
          </ul>
        )}

        {/* Running pill */}
        {isRunning && (
          <div style={{
            display: "inline-flex", alignItems: "center", gap: "0.35rem",
            marginTop: "0.35rem", padding: "0.2rem 0.55rem",
            background: "#fffbf0", border: `1px solid ${C.running}25`,
            borderRadius: 20, fontSize: "0.73rem", color: C.running,
          }}>
            <span className="pulse-live" style={{ width: 5, height: 5, borderRadius: "50%", background: C.running, display: "inline-block" }} />
            Working…
          </div>
        )}

        {/* Technical details expand */}
        {open && (
          <div className="slide-down" style={{
            marginTop: "0.5rem", padding: "0.75rem",
            background: C.surfaceMuted, border: `1px solid ${C.border}`,
            borderRadius: 10, fontSize: "0.73rem",
          }}>
            {item.steps.map((step, i) => (
              <div key={i} style={{ marginBottom: i < item.steps.length - 1 ? "0.875rem" : 0 }}>
                {item.steps.length > 1 && (
                  <p style={{ margin: "0 0 0.25rem", fontSize: "0.63rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: C.textMut }}>
                    Invocation {i + 1}
                  </p>
                )}
                {step.error && <p style={{ color: C.danger, margin: "0 0 0.25rem" }}>Error: {step.error}</p>}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.625rem" }}>
                  {(["input", "output"] as const).map(key => (
                    <div key={key}>
                      <p style={{ margin: "0 0 0.2rem", fontSize: "0.62rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: C.textMut }}>{key}</p>
                      <pre style={{ margin: 0, color: C.textSec, whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: "0.7rem", lineHeight: 1.5 }}>
                        {JSON.stringify(step[key], null, 2)}
                      </pre>
                    </div>
                  ))}
                </div>
                <p style={{ margin: "0.35rem 0 0", color: C.textMut, fontSize: "0.67rem" }}>
                  {step.duration_ms}ms · {step.agent} · {new Date(step.timestamp).toLocaleTimeString()}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Citation badge ─────────────────────────────────────────────────────────
function CitationBadge({ token, entry }: { token: string; entry: CitationEntry | undefined }) {
  const [hover, setHover] = useState(false);
  if (!entry) return <sup style={{ color: C.danger, fontSize: "0.63rem" }}>[?]</sup>;
  return (
    <span style={{ position: "relative", display: "inline" }}>
      <a
        href={`https://arxiv.org/abs/${entry.arxiv_id}`}
        target="_blank" rel="noreferrer"
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        style={{
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          verticalAlign: "super", width: 17, height: 17,
          fontSize: "0.58rem", fontWeight: 700, lineHeight: 1,
          background: hover ? C.info : "#eef4ff",
          color: hover ? "#fff" : C.info,
          borderRadius: "50%",
          textDecoration: "none", cursor: "pointer",
          border: `1px solid ${C.info}35`,
          margin: "0 1px", transition: "background 0.12s, color 0.12s",
        }}
      >
        {parseInt(token, 10)}
      </a>
      {hover && (
        <span style={{
          position: "absolute", bottom: "calc(100% + 10px)", left: "50%",
          transform: "translateX(-50%)", zIndex: 50,
          background: C.surface, border: `1px solid ${C.borderMd}`,
          borderRadius: 12, padding: "0.75rem 1rem",
          minWidth: 260, maxWidth: 340,
          boxShadow: "0 8px 32px rgba(0,0,0,0.12)",
          pointerEvents: "none", whiteSpace: "normal",
        }}>
          <p style={{ margin: 0, color: C.text, fontSize: "0.8rem", fontWeight: 600, lineHeight: 1.4 }}>{entry.title}</p>
          <p style={{ margin: "0.2rem 0 0", color: C.textSec, fontSize: "0.72rem" }}>{entry.authors.slice(0, 3).join(", ")}</p>
          <p style={{ margin: "0.18rem 0 0", color: C.info, fontSize: "0.7rem", fontWeight: 500 }}>arXiv:{entry.arxiv_id}</p>
        </span>
      )}
    </span>
  );
}

function SynthesisText({ text, citations }: { text: string; citations: Record<string, CitationEntry> }) {
  const parts = text.split(/(\[citation_\d{4}\])/g);
  return (
    <>
      {parts.map((part, i) => {
        const m = part.match(/^\[citation_(\d{4})\]$/);
        if (m) return <CitationBadge key={i} token={m[1]} entry={citations[m[1]]} />;
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}

// ── Subtle timestamp tooltip ───────────────────────────────────────────────
function TimestampHover({ date, children, align = "right", block = false }: {
  date: Date;
  children: React.ReactNode;
  align?: "left" | "right";
  block?: boolean;
}) {
  const [hover, setHover] = useState(false);
  const label = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <div
      style={{ position: "relative", display: block ? "block" : "inline-block" }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      {children}
      {hover && (
        <span style={{
          position: "absolute",
          top: "calc(100% + 5px)",
          ...(align === "right" ? { right: 0 } : { left: 0 }),
          background: "rgba(0,0,0,0.62)",
          color: "#fff",
          fontSize: "0.67rem",
          padding: "0.18rem 0.48rem",
          borderRadius: 5,
          whiteSpace: "nowrap",
          pointerEvents: "none",
          zIndex: 40,
          letterSpacing: "0.01em",
        }}>
          {label}
        </span>
      )}
    </div>
  );
}

// ── Animated waiting dots ──────────────────────────────────────────────────
function WaitingDots() {
  return (
    <span style={{ display: "inline-flex", gap: "3px", alignItems: "center", marginTop: "0.75rem" }}>
      {[0, 1, 2].map(i => (
        <span
          key={i}
          className="dot-pulse"
          style={{
            width: 5, height: 5, borderRadius: "50%",
            background: C.textMut,
            display: "inline-block",
            animationDelay: `${i * 0.18}s`,
          }}
        />
      ))}
    </span>
  );
}

// ── Synthesis block ────────────────────────────────────────────────────────
function SynthesisBlock({ review }: { review: Review }) {
  const hasContent = review.synthesis && review.synthesis.trim().length > 0;
  return (
    <div className="fade-in">
        {/* Synthesis text */}
        <div style={{
          background: C.surface,
          border: `1px solid ${C.border}`,
          borderRadius: 14,
          padding: "1.375rem 1.5rem",
          lineHeight: 1.9, fontSize: "0.9rem", color: hasContent ? C.text : C.textMut,
          boxShadow: "0 2px 12px rgba(0,0,0,0.04)",
          whiteSpace: "pre-wrap",
          overflowWrap: "break-word",
          wordBreak: "break-word",
          minWidth: 0,
          marginBottom: review.cited_papers.length > 0 ? "1rem" : 0,
        }}>
          {hasContent
            ? <SynthesisText text={review.synthesis} citations={review.citations} />
            : <span>No synthesis was generated for this topic.</span>
          }
          <p style={{ margin: "0.75rem 0 0", fontSize: "0.68rem", color: C.textMut }}>
            Hover a numbered badge to preview the source · click to open on arXiv
          </p>
        </div>

        {/* Sources */}
        {review.cited_papers.length > 0 && (
          <div>
            <p style={{ margin: "0 0 0.5rem", fontSize: "0.7rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.07em", color: C.textMut }}>
              Sources ({review.cited_papers.length})
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
              {review.cited_papers.map((p, i) => (
                <div key={p.paper_id} style={{
                  display: "flex", alignItems: "center", gap: "0.75rem",
                  padding: "0.75rem 0.875rem",
                  background: C.surface, border: `1px solid ${C.border}`,
                  borderRadius: 10, boxShadow: "0 1px 4px rgba(0,0,0,0.03)",
                }}>
                  <span style={{
                    width: 22, height: 22, borderRadius: "50%", flexShrink: 0,
                    background: "#f0f0ee", border: "1px solid rgba(0,0,0,0.08)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    fontSize: "0.68rem", fontWeight: 700, color: C.textMut,
                  }}>{i + 1}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <a href={`https://arxiv.org/abs/${p.arxiv_id}`} target="_blank" rel="noreferrer" style={{
                      color: C.text, textDecoration: "none", fontWeight: 600,
                      fontSize: "0.85rem", display: "block",
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}>
                      {p.title}
                    </a>
                    <p style={{ margin: "0.15rem 0 0", color: C.textMut, fontSize: "0.7rem" }}>
                      {p.authors.slice(0, 3).join(", ")} · <span style={{ color: C.info }}>arXiv:{p.arxiv_id}</span>
                    </p>
                  </div>
                  <span style={{
                    padding: "0.15rem 0.5rem", background: "#f5f5f3",
                    border: "1px solid rgba(0,0,0,0.07)", borderRadius: 20,
                    fontSize: "0.7rem", color: C.textSec, whiteSpace: "nowrap", flexShrink: 0,
                  }}>
                    {p.chunk_ids.length} passage{p.chunk_ids.length !== 1 ? "s" : ""}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
    </div>
  );
}

// ── Inner page (needs useSearchParams → must be inside Suspense) ───────────
function ResearchPageInner({ topicId }: { topicId: string }) {
  const searchParams   = useSearchParams();
  const jobId          = searchParams.get("job");
  const nameParam      = searchParams.get("name");

  // topicName: seeded from URL param immediately (no flash of ID)
  const [topicName,      setTopicName]      = useState(nameParam ? decodeURIComponent(nameParam) : "");
  const [pipelineStatus, setPipelineStatus] = useState<string>(jobId ? "connecting" : "done");
  const [steps,          setSteps]          = useState<TraceStep[]>([]);
  const [taskEvent,      setTaskEvent]      = useState<TaskEvent | null>(null);
  const [review,         setReview]         = useState<Review | null>(null);
  const [elapsed,        setElapsed]        = useState(0);
  const [reasoningOpen,  setReasoningOpen]  = useState(true);

  const startRef      = useRef<number | null>(null);
  const autoCollapsed = useRef(false);

  // ── Poll for review ──────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const res = await fetch(`${API}/api/v1/reviews/${topicId}`);
      if (cancelled || !res.ok) return;
      const data: Review = await res.json();
      setReview(data);
      if (!topicName) setTopicName(data.topic_name);
    };
    load();
    const interval = setInterval(load, 8_000);
    return () => { cancelled = true; clearInterval(interval); };
  }, [topicId]);

  // ── SSE connections (only when job is live) ───────────────────────────────
  useEffect(() => {
    if (!jobId) return;

    const taskEs = new EventSource(`${API}/api/v1/stream/task/${jobId}`);
    taskEs.onmessage = (e) => {
      try {
        const ev: TaskEvent = JSON.parse(e.data);
        setTaskEvent(ev);
        setPipelineStatus(ev.event);
        if (ev.topic && !topicName) setTopicName(ev.topic);
        if (ev.event === "started" && !startRef.current) startRef.current = Date.now();
        if ((ev.event === "done" || ev.event === "failed") && !autoCollapsed.current) {
          autoCollapsed.current = true;
          setTimeout(() => setReasoningOpen(false), 1500);
          taskEs.close();
        }
      } catch { /* ignore */ }
    };
    taskEs.onerror = () => setPipelineStatus(s => s === "connecting" ? "error" : s);

    const traceEs = new EventSource(`${API}/api/v1/stream/trace/${jobId}`);
    traceEs.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data);
        if (ev.event === "step") setSteps(prev => [...prev, ev as TraceStep]);
        if (ev.event === "done" || ev.event === "failed") traceEs.close();
      } catch { /* ignore */ }
    };

    return () => { taskEs.close(); traceEs.close(); };
  }, [jobId]);

  // ── Elapsed timer ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (pipelineStatus !== "started") return;
    const t = setInterval(() => {
      if (startRef.current) setElapsed(Math.round((Date.now() - startRef.current) / 1000));
    }, 1_000);
    return () => clearInterval(t);
  }, [pipelineStatus]);

  const isLive    = ["connecting", "queued", "started"].includes(pipelineStatus);
  const isFailed  = pipelineStatus === "failed";
  const isDone    = pipelineStatus === "done" || (!jobId && review !== null);

  const workflow    = buildWorkflow(steps, isLive);
  const currentItem = workflow.find(w => w.status === "running");

  // One-liner for the reasoning header
  const reasoningOneLiner = (() => {
    if (isFailed) return taskEvent?.error ?? "Pipeline failed";
    if (isLive)   return currentItem?.label ?? (pipelineStatus === "queued" ? "Waiting for a worker…" : "Starting…");
    if (taskEvent) {
      const p = taskEvent.papers_processed ?? review?.papers_processed ?? 0;
      const c = taskEvent.citations_verified ?? review?.citations_verified ?? 0;
      return `Researched ${p} paper${p !== 1 ? "s" : ""}, verified ${c} citation${c !== 1 ? "s" : ""}`;
    }
    if (review) {
      const p = review.papers_processed;
      const c = review.citations_verified;
      return `Researched ${p} paper${p !== 1 ? "s" : ""}, verified ${c} citation${c !== 1 ? "s" : ""}`;
    }
    return "Research complete";
  })();

  const displayName = topicName || topicId;

  return (
    <main>
      {/* Back nav */}
      <Link href="/" style={{ color: C.textMut, fontSize: "0.78rem", textDecoration: "none", display: "inline-block", marginBottom: "1.5rem" }}>
        ← New research
      </Link>

      {/*
        Layout contract:
        - Avatar is 28px wide, gap is 0.75rem → content column starts at calc(28px + 0.75rem)
        - User bubble row uses the same left padding so its right edge = content column right edge
        - All cards (reasoning, synthesis, sources) naturally share the same width inside the column
      */}

      {/* ── User bubble — offset left by avatar+gap so right edges align ── */}
      <div style={{
        display: "flex", justifyContent: "flex-end",
        marginBottom: "1.25rem",
        paddingLeft: "calc(28px + 0.75rem)",
      }}>
        <div style={{
          background: C.accent, color: "#fff",
          padding: "0.75rem 1.125rem",
          borderRadius: "18px 18px 4px 18px",
          maxWidth: "88%",
          fontSize: "0.95rem", fontWeight: 500, lineHeight: 1.4,
          boxShadow: "0 2px 12px rgba(255,107,0,0.18)",
        }}>
          {displayName}
        </div>
      </div>

      {/* ── AI response area ──────────────────────────────────────────── */}
      <div style={{ display: "flex", gap: "0.75rem", alignItems: "flex-start" }}>
        {/* RP avatar */}
        <div style={{
          width: 28, height: 28, borderRadius: 8, flexShrink: 0, marginTop: 2,
          background: "linear-gradient(135deg, #ff6b00, #ff9f0a)",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: "0.58rem", fontWeight: 800, color: "#fff", letterSpacing: "-0.02em",
        }}>
          RP
        </div>

        {/* Content column — reasoning + synthesis + sources all same width */}
        <div style={{ flex: 1, minWidth: 0 }}>

          {/* ── Reasoning card ────────────────────────────────────────── */}
          <div style={{
            background: C.surface,
            border: `1px solid ${C.border}`,
            borderRadius: 14,
            overflow: "hidden",
            marginBottom: review ? "1rem" : 0,
            boxShadow: "0 2px 12px rgba(0,0,0,0.04)",
          }}>
            {/* Header — always visible, clickable */}
            <button
              onClick={() => setReasoningOpen(o => !o)}
              style={{
                width: "100%", background: "none", border: "none", cursor: "pointer",
                padding: "0.7rem 1rem",
                display: "flex", alignItems: "center", gap: "0.5rem",
                textAlign: "left",
              }}
            >
              {isLive   && <span className="spinner-sm" />}
              {isDone   && <span style={{ fontSize: "0.8rem", color: C.success }}>✓</span>}
              {isFailed && <span style={{ fontSize: "0.8rem", color: C.danger }}>✗</span>}
              {!isLive && !isDone && !isFailed && <span className="spinner-sm" />}

              <span style={{ fontSize: "0.82rem", fontStyle: "italic", color: C.textSec, flexShrink: 0 }}>
                {isLive ? "Reasoning…" : "Reasoned"}
              </span>

              <span style={{
                fontSize: "0.8rem", color: C.textMut,
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                flex: 1,
              }}>
                — {reasoningOneLiner}
              </span>

              {isLive && elapsed > 0 && (
                <span style={{ fontSize: "0.73rem", color: C.textMut, flexShrink: 0, fontVariantNumeric: "tabular-nums" }}>
                  {elapsed}s
                </span>
              )}

              <span style={{ color: C.textMut, fontSize: "0.65rem", flexShrink: 0 }}>
                {reasoningOpen ? "▲" : "▼"}
              </span>
            </button>

            {/* Expanded workflow timeline */}
            {reasoningOpen && (
              <div className="slide-down" style={{
                padding: "0.25rem 1rem 1rem",
                borderTop: `1px solid ${C.border}`,
              }}>
                {steps.length === 0 && isLive ? (
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", padding: "0.75rem 0", color: C.textMut, fontSize: "0.82rem" }}>
                    <span className="spinner-sm" /> Connecting to pipeline…
                  </div>
                ) : (
                  <div style={{ paddingTop: "0.875rem" }}>
                    {workflow.map((item, i) => (
                      <TimelineItem key={item.id} item={item} isLast={i === workflow.length - 1} />
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* ── Synthesis ─────────────────────────────────────────────── */}
          {review && <SynthesisBlock review={review} />}

          {/* ── Waiting for synthesis (live, no review yet) ───────────── */}
          {isLive && !review && (
            <WaitingDots />
          )}

          {/* ── Failed state (no review) ──────────────────────────────── */}
          {isFailed && !review && (
            <div className="fade-in" style={{
              padding: "0.875rem 1rem",
              background: "#fef5f5", border: `1px solid ${C.danger}25`,
              borderRadius: 12, marginTop: "0.5rem",
            }}>
              <p style={{ margin: 0, color: C.danger, fontSize: "0.875rem" }}>
                {taskEvent?.error ?? "The pipeline encountered an error."}
              </p>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}

// ── Page export (Suspense boundary for useSearchParams) ────────────────────
export default function ResearchPage({ params }: { params: { topicId: string } }) {
  return (
    <Suspense fallback={
      <div style={{ display: "flex", alignItems: "center", gap: "0.625rem", color: "#999", fontSize: "0.875rem", marginTop: "2rem" }}>
        <span className="spinner" /> Loading…
      </div>
    }>
      <ResearchPageInner topicId={params.topicId} />
    </Suspense>
  );
}
