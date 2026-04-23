import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ResearchPulse",
  description: "Multi-agent arXiv research monitoring",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{
        fontFamily: "system-ui, -apple-system, sans-serif",
        maxWidth: 880,
        margin: "0 auto",
        padding: "0 1.25rem 3rem",
        background: "#1a1d21",
        color: "#d1d2d3",
        minHeight: "100vh",
      }}>
        <header style={{
          display: "flex",
          alignItems: "center",
          gap: "0.75rem",
          padding: "1.25rem 0",
          marginBottom: "2rem",
          borderBottom: "1px solid #414447",
        }}>
          <div style={{
            width: 30, height: 30, borderRadius: 8,
            background: "linear-gradient(135deg, #1264a3 0%, #1d9bd1 100%)",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: "0.7rem", fontWeight: 800, color: "#fff", flexShrink: 0,
            letterSpacing: "-0.02em",
          }}>
            RP
          </div>
          <div>
            <span style={{ fontWeight: 700, fontSize: "1rem", color: "#e8e9ea", letterSpacing: "-0.01em" }}>
              ResearchPulse
            </span>
            <span style={{ fontSize: "0.72rem", color: "#616061", marginLeft: "0.625rem" }}>
              multi-agent arXiv monitoring
            </span>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
