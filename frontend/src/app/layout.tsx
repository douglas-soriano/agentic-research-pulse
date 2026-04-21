import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "ResearchPulse",
  description: "Multi-agent arXiv research monitoring",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, sans-serif", maxWidth: 900, margin: "0 auto", padding: "2rem 1rem", background: "#0f1117", color: "#e2e8f0" }}>
        <header style={{ marginBottom: "2rem", borderBottom: "1px solid #2d3748", paddingBottom: "1rem" }}>
          <h1 style={{ margin: 0, fontSize: "1.5rem", color: "#63b3ed" }}>
            ResearchPulse
          </h1>
          <p style={{ margin: "0.25rem 0 0", color: "#718096", fontSize: "0.875rem" }}>
            Multi-agent arXiv research monitoring
          </p>
        </header>
        {children}
      </body>
    </html>
  );
}
