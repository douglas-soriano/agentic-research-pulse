"use client";
import { useState, useEffect } from "react";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ---- Types -----------------------------------------------------------------

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
  citations: Record<string, CitationEntry>;  // "0001" → CitationEntry
  cited_papers: CitedPaper[];
  papers_processed: number;
  claims_extracted: number;
  citations_verified: number;
  citations_rejected: number;
  version: number;
  updated_at: string;
}

// ---- Citation badge --------------------------------------------------------

function CitationBadge({
  token,
  entry,
}: {
  token: string;
  entry: CitationEntry | undefined;
}) {
  const [hover, setHover] = useState(false);

  if (!entry) {
    return (
      <span style={{ color: "#fc8181", fontSize: "0.7rem", marginLeft: 2 }}>
        [?{token}]
      </span>
    );
  }

  return (
    <span style={{ position: "relative", display: "inline-block" }}>
      <a
        href={`https://arxiv.org/abs/${entry.arxiv_id}`}
        target="_blank"
        rel="noreferrer"
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        style={{
          display: "inline-block",
          padding: "1px 5px",
          background: hover ? "#2b6cb0" : "#1e4e8c",
          color: "#bee3f8",
          borderRadius: 3,
          fontSize: "0.7rem",
          textDecoration: "none",
          marginLeft: 2,
          cursor: "pointer",
          transition: "background 0.1s",
        }}
      >
        {token}
      </a>
      {hover && (
        <span style={{
          position: "absolute",
          bottom: "calc(100% + 6px)",
          left: 0,
          zIndex: 10,
          background: "#1a202c",
          border: "1px solid #2d3748",
          borderRadius: 6,
          padding: "0.5rem 0.75rem",
          minWidth: 240,
          maxWidth: 360,
          boxShadow: "0 4px 12px rgba(0,0,0,0.5)",
          pointerEvents: "none",
        }}>
          <p style={{ margin: 0, color: "#e2e8f0", fontSize: "0.8rem", fontWeight: 600, lineHeight: 1.4 }}>
            {entry.title}
          </p>
          <p style={{ margin: "0.25rem 0 0", color: "#718096", fontSize: "0.7rem" }}>
            {entry.authors.slice(0, 3).join(", ")}
          </p>
          <p style={{ margin: "0.15rem 0 0", color: "#4a90d9", fontSize: "0.7rem" }}>
            {entry.arxiv_id}
          </p>
        </span>
      )}
    </span>
  );
}

// ---- Synthesis renderer ----------------------------------------------------
// Splits on [citation_XXXX] tokens and replaces each with a CitationBadge.

function SynthesisText({
  text,
  citations,
}: {
  text: string;
  citations: Record<string, CitationEntry>;
}) {
  const parts = text.split(/(\[citation_\d{4}\])/g);
  return (
    <>
      {parts.map((part, i) => {
        const match = part.match(/^\[citation_(\d{4})\]$/);
        if (match) {
          const token = match[1];
          return <CitationBadge key={i} token={token} entry={citations[token]} />;
        }
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}

// ---- Page ------------------------------------------------------------------

export default function ReviewPage({ params }: { params: { id: string } }) {
  const [review, setReview] = useState<Review | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    const load = async () => {
      const res = await fetch(`${API}/api/v1/reviews/${params.id}`);
      if (res.status === 404) { setNotFound(true); setLoading(false); return; }
      if (res.ok) { setReview(await res.json()); }
      setLoading(false);
    };
    load();
    // Poll every 10 s until we have a review, then slow down
    const interval = setInterval(() => {
      if (!review) load();
    }, 10000);
    return () => clearInterval(interval);
  }, [params.id]);

  if (loading) return <p style={{ color: "#718096" }}>Loading review…</p>;
  if (notFound) return (
    <div>
      <p style={{ color: "#718096" }}>Review not ready yet — pipeline may still be running.</p>
      <Link href="/" style={{ color: "#63b3ed" }}>← Back</Link>
    </div>
  );
  if (!review) return null;

  const verifiedCount = Object.keys(review.citations).length;

  return (
    <main>
      {/* Header */}
      <div style={{ marginBottom: "1.5rem" }}>
        <Link href="/" style={{ color: "#63b3ed", fontSize: "0.875rem" }}>← Back</Link>
        <h2 style={{ margin: "0.5rem 0 0.25rem", fontSize: "1.25rem" }}>{review.topic_name}</h2>
        <p style={{ color: "#718096", fontSize: "0.8rem", margin: 0 }}>
          Version {review.version}
          {" · "}{review.papers_processed} papers
          {" · "}{review.claims_extracted} claims
          {" · "}<span style={{ color: "#68d391" }}>{verifiedCount} citations</span>
          {review.citations_rejected > 0 && (
            <span style={{ color: "#fc8181" }}> · {review.citations_rejected} rejected</span>
          )}
          {" · "}Updated {new Date(review.updated_at).toLocaleString()}
        </p>
      </div>

      {/* Legend */}
      <p style={{ color: "#718096", fontSize: "0.75rem", marginBottom: "1rem" }}>
        Hover over a citation badge to see the source paper. Click to open on arXiv.
      </p>

      {/* Synthesis */}
      <section style={{ marginBottom: "2rem" }}>
        <div style={{
          background: "#1a202c",
          border: "1px solid #2d3748",
          borderRadius: 8,
          padding: "1.5rem",
          lineHeight: 1.8,
          whiteSpace: "pre-wrap",
        }}>
          <SynthesisText text={review.synthesis} citations={review.citations} />
        </div>
      </section>

      {/* Source papers */}
      <section>
        <h3 style={{ fontSize: "1rem", color: "#a0aec0", marginBottom: "1rem" }}>
          Cited Sources ({review.cited_papers.length})
        </h3>
        <div style={{ display: "grid", gap: "0.5rem" }}>
          {review.cited_papers.map((p) => (
            <div key={p.paper_id} style={{
              padding: "0.75rem 1rem",
              background: "#1a202c",
              border: "1px solid #2d3748",
              borderRadius: 6,
            }}>
              <a
                href={`https://arxiv.org/abs/${p.arxiv_id}`}
                target="_blank"
                rel="noreferrer"
                style={{ color: "#63b3ed", textDecoration: "none", fontWeight: 600, fontSize: "0.9rem" }}
              >
                {p.title}
              </a>
              <p style={{ margin: "0.2rem 0 0", color: "#718096", fontSize: "0.75rem" }}>
                {p.authors.slice(0, 3).join(", ")} — {p.arxiv_id}
                {" "}· {p.chunk_ids.length} cited passage{p.chunk_ids.length !== 1 ? "s" : ""}
              </p>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
