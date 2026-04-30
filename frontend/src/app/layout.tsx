import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ResearchPulse",
  description: "AI-powered research synthesis",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{
        margin: 0,
        background: "#f7f7f5",
        color: "#1a1a1a",
        fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif",
        minHeight: "100vh",
      }}>
        {}
        <header style={{
          position: "sticky", top: 0, zIndex: 100,
          background: "rgba(247,247,245,0.85)",
          backdropFilter: "blur(14px)",
          WebkitBackdropFilter: "blur(14px)",
          borderBottom: "1px solid rgba(0,0,0,0.07)",
          height: 52,
          display: "flex", alignItems: "center",
          padding: "0 1.5rem",
        }}>
          <div style={{
            maxWidth: 780, margin: "0 auto", width: "100%",
            display: "flex", alignItems: "center", gap: "0.625rem",
          }}>
            {}
            <div style={{
              width: 26, height: 26, borderRadius: 7,
              background: "linear-gradient(135deg, #ff6b00 0%, #ff9f0a 100%)",
              display: "flex", alignItems: "center", justifyContent: "center",
              flexShrink: 0,
            }}>
              <span style={{ color: "#fff", fontSize: "0.62rem", fontWeight: 800, letterSpacing: "-0.03em" }}>
                RP
              </span>
            </div>

            <span style={{ fontWeight: 700, fontSize: "0.95rem", color: "#1a1a1a", letterSpacing: "-0.01em" }}>
              ResearchPulse
            </span>

            <span style={{ fontSize: "0.72rem", color: "#aaa", marginLeft: 2 }}>
              · AI research synthesis
            </span>
          </div>
        </header>

        {}
        <div style={{ maxWidth: 780, margin: "0 auto", padding: "2.25rem 1.5rem 4rem" }}>
          {children}
        </div>
      </body>
    </html>
  );
}
