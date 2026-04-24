"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const C = {
  bg:      "#f7f7f5",
  surface: "#ffffff",
  border:  "rgba(0,0,0,0.08)",
  borderMd:"rgba(0,0,0,0.14)",
  text:    "#1a1a1a",
  textSec: "#555555",
  textMut: "#999999",
  accent:  "#ff6b00",
  success: "#2f9e6e",
  info:    "#2f80ed",
  danger:  "#e45b5b",
} as const;

interface Topic {
  id: string;
  name: string;
  last_fetched_at: string | null;
  created_at: string;
}

interface JobResponse {
  id: string;
  name: string;
  job_id: string | null;
  created_at: string;
}

export default function HomePage() {
  const router = useRouter();
  const [topics,    setTopics]    = useState<Topic[]>([]);
  const [name,      setName]      = useState("");
  const [maxPapers, setMaxPapers] = useState(5);
  const [loading,   setLoading]   = useState(false);
  const [error,     setError]     = useState<string | null>(null);

  const fetchTopics = async () => {
    const res = await fetch(`${API}/api/v1/topics`);
    if (res.ok) setTopics(await res.json());
  };

  useEffect(() => {
    fetchTopics();
    const interval = setInterval(fetchTopics, 15_000);
    return () => clearInterval(interval);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/api/v1/topics`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), max_papers: maxPapers }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data: JobResponse = await res.json();
      router.push(`/research/${data.id}${data.job_id ? `?job=${data.job_id}` : ""}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main>
      {/* ── Hero heading ─────────────────────────────────────────────── */}
      <div style={{ marginBottom: "2rem" }}>
        <h1 style={{
          margin: "0 0 0.375rem",
          fontSize: "1.6rem", fontWeight: 700,
          color: C.text, letterSpacing: "-0.02em", lineHeight: 1.2,
        }}>
          What do you want to research?
        </h1>
        <p style={{ margin: 0, fontSize: "0.9rem", color: C.textMut }}>
          Enter a topic and the AI will search papers, extract claims, and write a cited synthesis.
        </p>
      </div>

      {/* ── Search box ───────────────────────────────────────────────── */}
      <form onSubmit={handleSubmit} style={{ marginBottom: "2rem" }}>
        <div style={{
          display: "flex",
          background: C.surface,
          border: `1.5px solid ${loading ? C.accent : C.borderMd}`,
          borderRadius: 14,
          boxShadow: "0 4px 20px rgba(0,0,0,0.06)",
          overflow: "hidden",
          transition: "border-color 0.15s",
        }}>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. RAG for scientific papers"
            disabled={loading}
            style={{
              flex: 1, border: "none", outline: "none", background: "transparent",
              padding: "0.875rem 1rem",
              fontSize: "0.95rem", color: C.text,
            }}
          />
          <div style={{
            display: "flex", alignItems: "center", gap: "0.5rem",
            padding: "0 0.75rem",
            borderLeft: `1px solid ${C.border}`,
          }}>
            <select
              value={maxPapers}
              onChange={(e) => setMaxPapers(Number(e.target.value))}
              style={{
                border: "none", outline: "none", background: "transparent",
                fontSize: "0.82rem", color: C.textSec, cursor: "pointer",
                padding: "0.25rem",
              }}
            >
              {[3, 5, 8, 10].map((n) => (
                <option key={n} value={n}>{n} papers</option>
              ))}
            </select>
            <button
              type="submit"
              disabled={loading || !name.trim()}
              style={{
                padding: "0.45rem 1rem",
                background: loading || !name.trim() ? "#f0f0ee" : C.accent,
                color: loading || !name.trim() ? C.textMut : "#fff",
                border: "none", borderRadius: 8, cursor: loading || !name.trim() ? "not-allowed" : "pointer",
                fontSize: "0.85rem", fontWeight: 600, whiteSpace: "nowrap",
                transition: "background 0.15s",
                display: "flex", alignItems: "center", gap: "0.35rem",
              }}
            >
              {loading ? <><span className="spinner-sm" /> Starting…</> : "Run →"}
            </button>
          </div>
        </div>

        {/* Error */}
        {error && (
          <div style={{
            marginTop: "0.625rem", padding: "0.625rem 0.875rem",
            background: "#fef5f5", border: `1px solid ${C.danger}30`,
            borderRadius: 8, color: C.danger, fontSize: "0.83rem",
          }}>
            {error}
          </div>
        )}

      </form>

      {/* ── Topics list ──────────────────────────────────────────────── */}
      {topics.length > 0 && (
        <section>
          <p style={{
            margin: "0 0 0.75rem",
            fontSize: "0.72rem", fontWeight: 700, letterSpacing: "0.06em",
            textTransform: "uppercase", color: C.textMut,
          }}>
            Recent research ({topics.length})
          </p>

          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            {topics.map((t) => <TopicCard key={t.id} topic={t} />)}
          </div>
        </section>
      )}

      {topics.length === 0 && (
        <p style={{ color: C.textMut, fontSize: "0.875rem", textAlign: "center", marginTop: "3rem" }}>
          No topics yet — add one above to start your first research run.
        </p>
      )}
    </main>
  );
}

// ── Topic card ──────────────────────────────────────────────────────────────
function TopicCard({ topic }: { topic: Topic }) {
  const updated = topic.last_fetched_at ? new Date(topic.last_fetched_at) : null;
  const hasData = !!updated;

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: "0.875rem",
      padding: "0.875rem 1rem",
      background: "#ffffff",
      border: "1px solid rgba(0,0,0,0.08)",
      borderRadius: 12,
      boxShadow: "0 1px 4px rgba(0,0,0,0.04)",
      transition: "box-shadow 0.15s",
    }}>
      {/* Status dot */}
      <div style={{
        width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
        background: hasData ? "#2f9e6e" : "rgba(0,0,0,0.15)",
      }} />

      {/* Info */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontWeight: 600, fontSize: "0.9rem", color: "#1a1a1a",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {topic.name}
        </div>
        <div style={{ fontSize: "0.72rem", color: "#aaa", marginTop: 2 }}>
          {updated
            ? `Updated ${updated.toLocaleDateString()} at ${updated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
            : `Added ${new Date(topic.created_at).toLocaleDateString()}`}
        </div>
      </div>

      {/* Action */}
      <Link
        href={`/research/${topic.id}`}
        style={{
          padding: "0.35rem 0.75rem",
          background: hasData ? "#f0faf6" : "#f5f5f3",
          color: hasData ? "#2f9e6e" : "#999",
          border: `1px solid ${hasData ? "#2f9e6e30" : "rgba(0,0,0,0.08)"}`,
          borderRadius: 7,
          textDecoration: "none",
          fontSize: "0.78rem", fontWeight: 600,
          whiteSpace: "nowrap", flexShrink: 0,
        }}
      >
        {hasData ? "View research" : "Pending…"}
      </Link>
    </div>
  );
}
