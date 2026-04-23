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

// ── Page ───────────────────────────────────────────────────────────────────
export default function HomePage() {
  const [topics,    setTopics]    = useState<Topic[]>([]);
  const [name,      setName]      = useState("");
  const [maxPapers, setMaxPapers] = useState(5);
  const [loading,   setLoading]   = useState(false);
  const [lastJobId, setLastJobId] = useState<string | null>(null);
  const [error,     setError]     = useState<string | null>(null);

  const fetchTopics = async () => {
    const res = await fetch(`${API}/api/v1/topics`);
    if (res.ok) setTopics(await res.json());
  };

  useEffect(() => {
    fetchTopics();
    const interval = setInterval(fetchTopics, 15000);
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
      setLastJobId(data.job_id);
      setName("");
      await fetchTopics();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <main>
      {/* New topic form */}
      <section style={{ marginBottom: "2.5rem" }}>
        <Label>New research topic</Label>
        <form
          onSubmit={handleSubmit}
          style={{ display: "flex", gap: "0.625rem", flexWrap: "wrap", marginTop: "0.625rem" }}
        >
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. RAG for scientific papers"
            style={{
              flex: 1, minWidth: 220,
              padding: "0.55rem 0.875rem",
              background: C.card,
              border: `1px solid ${C.border}`,
              borderRadius: 6,
              color: C.textPri,
              fontSize: "0.9rem",
              outline: "none",
            }}
            disabled={loading}
          />
          <select
            value={maxPapers}
            onChange={(e) => setMaxPapers(Number(e.target.value))}
            style={{
              flex: "none", width: 120,
              padding: "0.55rem 0.75rem",
              background: C.card,
              border: `1px solid ${C.border}`,
              borderRadius: 6,
              color: C.textPri,
              fontSize: "0.9rem",
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
              padding: "0.55rem 1.25rem",
              background: loading || !name.trim() ? C.card : C.blueDark,
              color: loading || !name.trim() ? C.textMut : "#fff",
              border: `1px solid ${loading || !name.trim() ? C.border : C.blueDark}`,
              borderRadius: 6,
              cursor: loading || !name.trim() ? "not-allowed" : "pointer",
              fontSize: "0.9rem",
              fontWeight: 600,
              whiteSpace: "nowrap",
              transition: "background 0.15s",
            }}
          >
            {loading ? "Starting…" : "Run pipeline"}
          </button>
        </form>

        {error && (
          <div style={{
            marginTop: "0.75rem", padding: "0.625rem 0.875rem",
            background: "#2d1515", border: `1px solid ${C.red}50`,
            borderRadius: 6, color: C.red, fontSize: "0.85rem",
          }}>
            {error}
          </div>
        )}

        {lastJobId && (
          <div style={{
            marginTop: "0.75rem", padding: "0.625rem 0.875rem",
            background: "#122010", border: `1px solid ${C.green}40`,
            borderRadius: 6, fontSize: "0.85rem", color: C.green,
            display: "flex", alignItems: "center", gap: "0.625rem",
          }}>
            <span className="pulse-live" style={{
              width: 7, height: 7, borderRadius: "50%",
              background: C.green, display: "inline-block", flexShrink: 0,
            }} />
            Pipeline started —{" "}
            <Link
              href={`/traces/${lastJobId}`}
              style={{ color: C.blue, textDecoration: "none", fontWeight: 600 }}
            >
              Watch live trace →
            </Link>
          </div>
        )}
      </section>

      {/* Topic list */}
      <section>
        <Label>Topics ({topics.length})</Label>
        {topics.length === 0 ? (
          <p style={{ color: C.textMut, fontSize: "0.875rem", marginTop: "0.75rem" }}>
            No topics yet — add one above to start the pipeline.
          </p>
        ) : (
          <div style={{ display: "grid", gap: "0.5rem", marginTop: "0.625rem" }}>
            {topics.map((t) => <TopicCard key={t.id} topic={t} />)}
          </div>
        )}
      </section>
    </main>
  );
}

// ── Topic card ─────────────────────────────────────────────────────────────
function TopicCard({ topic }: { topic: Topic }) {
  const updated = topic.last_fetched_at ? new Date(topic.last_fetched_at) : null;

  return (
    <div style={{
      padding: "0.875rem 1rem",
      background: C.card,
      border: `1px solid ${C.border}`,
      borderRadius: 8,
      display: "flex", alignItems: "center", gap: "0.875rem",
    }}>
      <div style={{
        width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
        background: updated ? C.green : C.textMut,
      }} />

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontWeight: 600, fontSize: "0.9rem", color: C.textPri,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {topic.name}
        </div>
        <div style={{ fontSize: "0.72rem", color: C.textMut, marginTop: 2 }}>
          {updated
            ? `Updated ${updated.toLocaleDateString()} ${updated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
            : `Added ${new Date(topic.created_at).toLocaleDateString()}`
          }
        </div>
      </div>

      <Link
        href={`/review/${topic.id}`}
        style={{
          padding: "0.35rem 0.875rem",
          background: C.surface,
          color: C.blue,
          border: `1px solid ${C.border}`,
          borderRadius: 5,
          textDecoration: "none",
          fontSize: "0.8rem",
          fontWeight: 600,
          whiteSpace: "nowrap",
          flexShrink: 0,
        }}
      >
        View review
      </Link>
    </div>
  );
}

// ── Label ──────────────────────────────────────────────────────────────────
function Label({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: "0.7rem", fontWeight: 700,
      color: C.textSec, letterSpacing: "0.06em",
      textTransform: "uppercase", marginBottom: "0.5rem",
    }}>
      {children}
    </div>
  );
}
