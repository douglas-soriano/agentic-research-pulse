"use client";
import { useState, useEffect } from "react";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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
  const [topics, setTopics] = useState<Topic[]>([]);
  const [name, setName] = useState("");
  const [maxPapers, setMaxPapers] = useState(8);
  const [loading, setLoading] = useState(false);
  const [lastJobId, setLastJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchTopics = async () => {
    const res = await fetch(`${API}/api/v1/topics`);
    if (res.ok) setTopics(await res.json());
  };

  useEffect(() => { fetchTopics(); }, []);

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
      <section style={{ marginBottom: "2rem" }}>
        <h2 style={{ fontSize: "1.1rem", marginBottom: "1rem", color: "#a0aec0" }}>
          Add Research Topic
        </h2>
        <form onSubmit={handleSubmit} style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. RAG for scientific papers"
            style={inputStyle}
            disabled={loading}
          />
          <select
            value={maxPapers}
            onChange={(e) => setMaxPapers(Number(e.target.value))}
            style={{ ...inputStyle, width: 130 }}
          >
            {[3, 5, 8, 10].map((n) => (
              <option key={n} value={n}>{n} papers</option>
            ))}
          </select>
          <button type="submit" disabled={loading || !name.trim()} style={btnStyle}>
            {loading ? "Enqueuing…" : "Start Pipeline"}
          </button>
        </form>
        {error && <p style={{ color: "#fc8181", marginTop: "0.5rem" }}>{error}</p>}
        {lastJobId && (
          <p style={{ color: "#68d391", marginTop: "0.5rem", fontSize: "0.875rem" }}>
            Pipeline started. <Link href={`/traces/${lastJobId}`} style={{ color: "#63b3ed" }}>View trace →</Link>
          </p>
        )}
      </section>

      <section>
        <h2 style={{ fontSize: "1.1rem", marginBottom: "1rem", color: "#a0aec0" }}>
          Topics ({topics.length})
        </h2>
        {topics.length === 0 && (
          <p style={{ color: "#718096" }}>No topics yet. Add one above to start.</p>
        )}
        <div style={{ display: "grid", gap: "0.75rem" }}>
          {topics.map((t) => (
            <div key={t.id} style={cardStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <strong style={{ fontSize: "1rem" }}>{t.name}</strong>
                  <p style={{ margin: "0.25rem 0 0", fontSize: "0.75rem", color: "#718096" }}>
                    Added {new Date(t.created_at).toLocaleString()}
                    {t.last_fetched_at && ` · Last updated ${new Date(t.last_fetched_at).toLocaleString()}`}
                  </p>
                </div>
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <Link href={`/review/${t.id}`} style={linkBtnStyle}>Review</Link>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}

const inputStyle: React.CSSProperties = {
  flex: 1,
  minWidth: 200,
  padding: "0.5rem 0.75rem",
  background: "#1a202c",
  border: "1px solid #2d3748",
  borderRadius: 6,
  color: "#e2e8f0",
  fontSize: "0.9rem",
};

const btnStyle: React.CSSProperties = {
  padding: "0.5rem 1.25rem",
  background: "#3182ce",
  color: "white",
  border: "none",
  borderRadius: 6,
  cursor: "pointer",
  fontSize: "0.9rem",
};

const cardStyle: React.CSSProperties = {
  padding: "1rem",
  background: "#1a202c",
  border: "1px solid #2d3748",
  borderRadius: 8,
};

const linkBtnStyle: React.CSSProperties = {
  padding: "0.25rem 0.75rem",
  background: "#2d3748",
  color: "#63b3ed",
  borderRadius: 4,
  textDecoration: "none",
  fontSize: "0.8rem",
};
