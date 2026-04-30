"use client";
import { useState, useEffect } from "react";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const C = {
  bg:      "#f7f7f5",
  surface: "#ffffff",
  surfaceMuted: "#fafafa",
  border:  "rgba(0,0,0,0.08)",
  borderMd:"rgba(0,0,0,0.13)",
  text:    "#1a1a1a",
  textSec: "#555555",
  textMut: "#999999",
  accent:  "#ff6b00",
  success: "#2f9e6e",
  running: "#d4a017",
  info:    "#2f80ed",
  danger:  "#e45b5b",
} as const;


interface CitationEntry {
  paper_id: string;
  arxiv_id: string;
  title:    string;
  authors:  string[];
  chunk_id: string;
}

interface CitedPaper {
  paper_id:  string;
  arxiv_id:  string;
  title:     string;
  authors:   string[];
  chunk_ids: string[];
}

interface Review {
  id:                  string;
  topic_id:            string;
  topic_name:          string;
  synthesis:           string;
  citations:           Record<string, CitationEntry>;
  cited_papers:        CitedPaper[];
  papers_processed:    number;
  claims_extracted:    number;
  citations_verified:  number;
  citations_rejected:  number;
  version:             number;
  updated_at:          string;
}


function CitationBadge({
  token, entry,
}: {
  token: string;
  entry: CitationEntry | undefined;
}) {
  const [hover, setHover] = useState(false);

  if (!entry) {
    return <sup style={{ color: C.danger, fontSize: "0.65rem" }}>[?]</sup>;
  }

  const num = parseInt(token, 10);

  return (
    <span style={{ position: "relative", display: "inline" }}>
      <a
        href={`https://arxiv.org/abs/${entry.arxiv_id}`}
        target="_blank" rel="noreferrer"
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        style={{
          display: "inline-flex",
          alignItems: "center", justifyContent: "center",
          verticalAlign: "super",
          width: 18, height: 18,
          fontSize: "0.6rem", fontWeight: 700, lineHeight: 1,
          background: hover ? C.info : "#eef4ff",
          color: hover ? "#fff" : C.info,
          borderRadius: "50%",
          textDecoration: "none",
          cursor: "pointer",
          border: `1px solid ${C.info}40`,
          margin: "0 1px",
          transition: "background 0.12s, color 0.12s",
          flexShrink: 0,
        }}
      >
        {num}
      </a>

      {hover && (
        <span style={{
          position: "absolute",
          bottom: "calc(100% + 10px)",
          left: "50%", transform: "translateX(-50%)",
          zIndex: 50,
          background: C.surface,
          border: `1px solid ${C.borderMd}`,
          borderRadius: 12,
          padding: "0.75rem 1rem",
          minWidth: 260, maxWidth: 360,
          boxShadow: "0 8px 32px rgba(0,0,0,0.12)",
          pointerEvents: "none", whiteSpace: "normal",
        }}>
          <p style={{ margin: 0, color: C.text, fontSize: "0.8rem", fontWeight: 600, lineHeight: 1.4 }}>
            {entry.title}
          </p>
          <p style={{ margin: "0.25rem 0 0", color: C.textSec, fontSize: "0.72rem" }}>
            {entry.authors.slice(0, 3).join(", ")}
          </p>
          <p style={{ margin: "0.2rem 0 0", color: C.info, fontSize: "0.72rem", fontWeight: 500 }}>
            arXiv:{entry.arxiv_id}
          </p>
          <p style={{ margin: "0.4rem 0 0", color: C.textMut, fontSize: "0.7rem" }}>
            Click to open on arXiv →
          </p>
        </span>
      )}
    </span>
  );
}


function SynthesisText({
  text, citations,
}: {
  text: string;
  citations: Record<string, CitationEntry>;
}) {
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


export default function ReviewPage({ params }: { params: { id: string } }) {
  const [review,   setReview]   = useState<Review | null>(null);
  const [loading,  setLoading]  = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const res = await fetch(`${API}/api/v1/reviews/${params.id}`);
      if (cancelled) return;
      if (res.ok) {
        setReview(await res.json());
        setNotFound(false);
        setLoading(false);
      } else if (res.status === 404) {
        setNotFound(true);
        setLoading(false);
      } else {
        setLoading(false);
      }
    };
    load();
    const interval = setInterval(load, 10_000);
    return () => { cancelled = true; clearInterval(interval); };
  }, [params.id]);


  if (loading) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: "0.625rem", color: C.textSec, fontSize: "0.9rem", marginTop: "3rem", justifyContent: "center" }}>
        <span className="spinner" /> Loading review…
      </div>
    );
  }


  if (notFound) {
    return (
      <div style={{
        padding: "2rem", background: C.surface,
        border: `1px solid ${C.border}`, borderRadius: 16,
        textAlign: "center", boxShadow: "0 2px 12px rgba(0,0,0,0.04)",
      }}>
        <p style={{ color: C.textSec, fontSize: "0.9rem", margin: "0 0 1rem" }}>
          Review not ready yet — the pipeline may still be running.
        </p>
        <Link href="/" style={{ color: C.accent, fontSize: "0.85rem", textDecoration: "none", fontWeight: 600 }}>
          ← Back to topics
        </Link>
      </div>
    );
  }

  if (!review) return null;

  const updated      = new Date(review.updated_at);
  const citationCount = Object.keys(review.citations).length;

  return (
    <main>
      {}
      <Link href="/" style={{
        color: C.textMut, fontSize: "0.8rem", textDecoration: "none",
        display: "inline-block", marginBottom: "1rem",
      }}>
        ← Back
      </Link>

      {}
      <h2 style={{
        margin: "0 0 0.75rem",
        fontSize: "1.5rem", fontWeight: 700, letterSpacing: "-0.02em",
        color: C.text, lineHeight: 1.25,
      }}>
        {review.topic_name}
      </h2>

      {}
      <div style={{ display: "flex", gap: "1.25rem", flexWrap: "wrap", marginBottom: "0.625rem" }}>
        {[
          { value: review.papers_processed,  label: "papers",    color: C.info    },
          { value: review.claims_extracted,   label: "claims",    color: C.running },
          { value: citationCount,             label: "citations", color: C.success },
        ].map(({ value, label, color }) => (
          <div key={label} style={{ display: "flex", alignItems: "baseline", gap: "0.3rem" }}>
            <span style={{ fontSize: "1.1rem", fontWeight: 700, color, lineHeight: 1 }}>{value}</span>
            <span style={{ fontSize: "0.75rem", color: C.textMut }}>{label}</span>
          </div>
        ))}
      </div>

      <p style={{ margin: "0 0 1.75rem", color: C.textMut, fontSize: "0.72rem" }}>
        Version {review.version}
        {" · "}Updated {updated.toLocaleDateString()} at{" "}
        {updated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
      </p>

      {}
      <section style={{ marginBottom: "2rem" }}>
        <SectionLabel>Synthesis</SectionLabel>

        <div style={{
          marginTop: "0.75rem",
          background: C.surface,
          border: `1px solid ${C.border}`,
          borderRadius: 16,
          padding: "1.5rem 1.75rem",
          lineHeight: 1.9, fontSize: "0.925rem", color: C.text,
          boxShadow: "0 2px 12px rgba(0,0,0,0.04)",
          whiteSpace: "pre-wrap",
        }}>
          <SynthesisText text={review.synthesis} citations={review.citations} />
        </div>

        <p style={{ color: C.textMut, fontSize: "0.7rem", marginTop: "0.5rem" }}>
          Hover a numbered badge to preview the source — click to open on arXiv.
        </p>
      </section>

      {}
      {review.cited_papers.length > 0 && (
        <section>
          <SectionLabel>Sources ({review.cited_papers.length})</SectionLabel>

          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem", marginTop: "0.75rem" }}>
            {review.cited_papers.map((p, i) => (
              <div key={p.paper_id} style={{
                display: "flex", alignItems: "center", gap: "0.875rem",
                padding: "0.875rem 1rem",
                background: C.surface,
                border: `1px solid ${C.border}`,
                borderRadius: 12,
                boxShadow: "0 1px 4px rgba(0,0,0,0.03)",
              }}>
                {}
                <span style={{
                  width: 24, height: 24, borderRadius: "50%",
                  background: "#f0f0ee", border: "1px solid rgba(0,0,0,0.08)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: "0.7rem", fontWeight: 700, color: C.textMut,
                  flexShrink: 0,
                }}>
                  {i + 1}
                </span>

                {}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <a
                    href={`https://arxiv.org/abs/${p.arxiv_id}`}
                    target="_blank" rel="noreferrer"
                    style={{
                      color: C.text, textDecoration: "none", fontWeight: 600,
                      fontSize: "0.875rem", display: "block",
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}
                  >
                    {p.title}
                  </a>
                  <p style={{ margin: "0.2rem 0 0", color: C.textMut, fontSize: "0.73rem" }}>
                    {p.authors.slice(0, 3).join(", ")}
                    {" · "}
                    <span style={{ color: C.info }}>arXiv:{p.arxiv_id}</span>
                  </p>
                </div>

                {}
                <span style={{
                  padding: "0.2rem 0.55rem",
                  background: "#f5f5f3",
                  border: "1px solid rgba(0,0,0,0.07)",
                  borderRadius: 20,
                  fontSize: "0.72rem", color: C.textSec,
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


function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: "0.72rem", fontWeight: 700,
      letterSpacing: "0.07em", textTransform: "uppercase",
      color: C.textMut,
    }}>
      {children}
    </div>
  );
}
