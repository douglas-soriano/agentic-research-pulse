"use client";
import { useState, useEffect } from "react";
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
interface CitationEntry {
  paper_id: string;
  arxiv_id: string;
  title: string;
  authors: string[];
  chunk_id: string;
}

interface CitedPaper {
  paper_id: string;
  arxiv_id: string;
  title: string;
  authors: string[];
  chunk_ids: string[];
}

interface Review {
  id: string;
  topic_id: string;
  topic_name: string;
  synthesis: string;
  citations: Record<string, CitationEntry>;
  cited_papers: CitedPaper[];
  papers_processed: number;
  claims_extracted: number;
  citations_verified: number;
  citations_rejected: number;
  version: number;
  updated_at: string;
}

// ── Citation badge ─────────────────────────────────────────────────────────
function CitationBadge({ token, entry }: { token: string; entry: CitationEntry | undefined }) {
  const [hover, setHover] = useState(false);

  if (!entry) {
    return (
      <sup style={{ color: C.red, fontSize: "0.65rem", margin: "0 1px" }}>[?]</sup>
    );
  }

  return (
    <span style={{ position: "relative", display: "inline" }}>
      <a
        href={`https://arxiv.org/abs/${entry.arxiv_id}`}
        target="_blank"
        rel="noreferrer"
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        style={{
          display: "inline-block",
          verticalAlign: "super",
          fontSize: "0.65rem",
          lineHeight: 1,
          padding: "1px 5px",
          background: hover ? C.blueDark : "#1264a322",
          color: C.blue,
          borderRadius: 3,
          textDecoration: "none",
          cursor: "pointer",
          border: `1px solid ${C.blueDark}66`,
          fontWeight: 600,
          margin: "0 1px",
          transition: "background 0.12s",
        }}
      >
        {parseInt(token, 10)}
      </a>
      {hover && (
        <span style={{
          position: "absolute",
          bottom: "calc(100% + 8px)",
          left: "50%",
          transform: "translateX(-50%)",
          zIndex: 20,
          background: C.card,
          border: `1px solid ${C.border}`,
          borderRadius: 8,
          padding: "0.625rem 0.875rem",
          minWidth: 240,
          maxWidth: 340,
          boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
          pointerEvents: "none",
          whiteSpace: "normal",
        }}>
          <p style={{ margin: 0, color: C.textPri, fontSize: "0.8rem", fontWeight: 600, lineHeight: 1.4 }}>
            {entry.title}
          </p>
          <p style={{ margin: "0.25rem 0 0", color: C.textSec, fontSize: "0.72rem" }}>
            {entry.authors.slice(0, 3).join(", ")}
          </p>
          <p style={{ margin: "0.15rem 0 0", color: C.blue, fontSize: "0.72rem", fontWeight: 500 }}>
            {entry.arxiv_id}
          </p>
        </span>
      )}
    </span>
  );
}

// ── Synthesis renderer ─────────────────────────────────────────────────────
function SynthesisText({ text, citations }: { text: string; citations: Record<string, CitationEntry> }) {
  const parts = text.split(/(\[citation_\d{4}\])/g);
  return (
    <>
      {parts.map((part, i) => {
        const match = part.match(/^\[citation_(\d{4})\]$/);
        if (match) {
          return <CitationBadge key={i} token={match[1]} entry={citations[match[1]]} />;
        }
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}

// ── Stat chip ──────────────────────────────────────────────────────────────
function StatChip({ value, label, color }: { value: number | string; label: string; color: string }) {
  return (
    <div style={{
      display: "inline-flex", alignItems: "baseline", gap: "0.3rem",
      padding: "0.3rem 0.75rem",
      background: color + "18",
      border: `1px solid ${color}35`,
      borderRadius: 6,
    }}>
      <span style={{ fontSize: "1rem", fontWeight: 700, color, lineHeight: 1 }}>{value}</span>
      <span style={{ fontSize: "0.72rem", color: C.textMut }}>{label}</span>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────
export default function ReviewPage({ params }: { params: { id: string } }) {
  const [review,   setReview]   = useState<Review | null>(null);
  const [loading,  setLoading]  = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    let stopped = false;
    const load = async () => {
      const res = await fetch(`${API}/api/v1/reviews/${params.id}`);
      if (stopped) return;
      if (res.ok) {
        setReview(await res.json());
        setNotFound(false);
        setLoading(false);
        return;
      }
      if (res.status === 404) setNotFound(true);
      setLoading(false);
    };
    load();
    const interval = setInterval(load, 10000);
    return () => { stopped = true; clearInterval(interval); };
  }, [params.id]);

  if (loading) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: "0.625rem", color: C.textSec, fontSize: "0.875rem" }}>
        <span className="spinner" /> Loading review…
      </div>
    );
  }

  if (notFound) {
    return (
      <div style={{
        padding: "1.5rem",
        background: C.card, border: `1px solid ${C.border}`, borderRadius: 10,
        textAlign: "center",
      }}>
        <p style={{ color: C.textSec, fontSize: "0.9rem", margin: "0 0 0.875rem" }}>
          Review not ready yet — the pipeline may still be running.
        </p>
        <Link href="/" style={{ color: C.blue, fontSize: "0.85rem", textDecoration: "none", fontWeight: 600 }}>
          ← Back to topics
        </Link>
      </div>
    );
  }

  if (!review) return null;

  const updated = new Date(review.updated_at);
  const citationCount = Object.keys(review.citations).length;

  return (
    <main>
      {/* Header */}
      <div style={{ marginBottom: "1.75rem" }}>
        <Link href="/" style={{ color: C.textMut, fontSize: "0.8rem", textDecoration: "none" }}>
          ← Back
        </Link>
        <h2 style={{
          margin: "0.5rem 0 0.875rem", fontSize: "1.25rem",
          color: C.textPri, fontWeight: 700, letterSpacing: "-0.015em", lineHeight: 1.3,
        }}>
          {review.topic_name}
        </h2>

        <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", marginBottom: "0.625rem" }}>
          <StatChip value={review.papers_processed}  label="papers"    color={C.blue}  />
          <StatChip value={review.claims_extracted}   label="claims"    color={C.amber} />
          <StatChip value={citationCount}             label="citations" color={C.green} />
          {review.citations_rejected > 0 && (
            <StatChip value={review.citations_rejected} label="rejected" color={C.red} />
          )}
        </div>

        <p style={{ color: C.textMut, fontSize: "0.72rem", margin: 0 }}>
          Version {review.version}
          {" · "}Updated {updated.toLocaleDateString()}{" "}
          {updated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </p>
      </div>

      {/* Synthesis */}
      <section style={{ marginBottom: "2rem" }}>
        <SectionLabel>Synthesis</SectionLabel>
        <div style={{
          marginTop: "0.625rem",
          background: C.card,
          border: `1px solid ${C.border}`,
          borderRadius: 10,
          padding: "1.375rem 1.5rem",
          lineHeight: 1.9,
          fontSize: "0.9rem",
          color: C.textPri,
          whiteSpace: "pre-wrap",
        }}>
          <SynthesisText text={review.synthesis} citations={review.citations} />
        </div>
        <p style={{ color: C.textMut, fontSize: "0.7rem", marginTop: "0.4rem" }}>
          Hover a citation badge to see the source — click to open on arXiv.
        </p>
      </section>

      {/* Cited papers */}
      {review.cited_papers.length > 0 && (
        <section>
          <SectionLabel>Cited sources ({review.cited_papers.length})</SectionLabel>
          <div style={{ display: "grid", gap: "0.4rem", marginTop: "0.625rem" }}>
            {review.cited_papers.map((p, i) => (
              <div key={p.paper_id} style={{
                display: "grid",
                gridTemplateColumns: "28px 1fr auto",
                alignItems: "center",
                gap: "0.75rem",
                padding: "0.75rem 1rem",
                background: C.card,
                border: `1px solid ${C.border}`,
                borderRadius: 7,
              }}>
                <span style={{
                  fontSize: "0.7rem", fontWeight: 700, color: C.textMut,
                  fontVariantNumeric: "tabular-nums", textAlign: "center",
                }}>
                  {i + 1}
                </span>
                <div style={{ minWidth: 0 }}>
                  <a
                    href={`https://arxiv.org/abs/${p.arxiv_id}`}
                    target="_blank"
                    rel="noreferrer"
                    style={{
                      color: C.blue, textDecoration: "none", fontWeight: 600,
                      fontSize: "0.875rem", display: "block",
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}
                  >
                    {p.title}
                  </a>
                  <p style={{ margin: "0.2rem 0 0", color: C.textMut, fontSize: "0.73rem" }}>
                    {p.authors.slice(0, 3).join(", ")} · {p.arxiv_id}
                  </p>
                </div>
                <span style={{
                  fontSize: "0.7rem", color: C.textMut,
                  whiteSpace: "nowrap", flexShrink: 0,
                }}>
                  {p.chunk_ids.length} passage{p.chunk_ids.length !== 1 ? "s" : ""}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}

// ── Section label ──────────────────────────────────────────────────────────
function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: "0.7rem", fontWeight: 700,
      color: C.textSec, letterSpacing: "0.06em",
      textTransform: "uppercase",
    }}>
      {children}
    </div>
  );
}
