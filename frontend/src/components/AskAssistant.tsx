import React, { useState } from "react";
import { postAsk, type AskResponse } from "../api";

interface Props {
  propertyId: string;
}

const EXAMPLE_QUESTIONS = [
  "Kitne bookings confirmed hain?",
  "Is month ka total revenue kya hai?",
  "MMT se kitne bookings aaye?",
  "How many no-shows last week?",
  "Rate management kaise karte hain?",
];

export function AskAssistant({ propertyId }: Props) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async (q?: string) => {
    const text = (q ?? question).trim();
    if (!text) return;
    setLoading(true);
    setResult(null);
    setError(null);
    try {
      const res = await postAsk(propertyId, text);
      setResult(res.data);
    } catch (e: unknown) {
      setError("Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Input */}
      <div style={{ display: "flex", gap: 8 }}>
        <input
          value={question}
          onChange={e => setQuestion(e.target.value)}
          onKeyDown={e => e.key === "Enter" && submit()}
          placeholder="Koi bhi sawal poochiye… (Hinglish / English)"
          style={{
            flex: 1,
            background: "#1e293b",
            border: "1px solid #334155",
            borderRadius: 8,
            padding: "10px 14px",
            color: "#f1f5f9",
            fontSize: 14,
            outline: "none",
          }}
        />
        <button
          onClick={() => submit()}
          disabled={loading || !question.trim()}
          style={{
            background: loading ? "#334155" : "#6366f1",
            color: "#fff",
            border: "none",
            borderRadius: 8,
            padding: "10px 20px",
            cursor: loading ? "not-allowed" : "pointer",
            fontWeight: 600,
            fontSize: 14,
            transition: "background 0.2s",
          }}
        >
          {loading ? "…" : "Ask"}
        </button>
      </div>

      {/* Example chips */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {EXAMPLE_QUESTIONS.map(q => (
          <button
            key={q}
            onClick={() => { setQuestion(q); submit(q); }}
            style={{
              background: "#1e293b",
              border: "1px solid #334155",
              borderRadius: 20,
              padding: "4px 12px",
              color: "#94a3b8",
              fontSize: 12,
              cursor: "pointer",
            }}
          >
            {q}
          </button>
        ))}
      </div>

      {/* Loading */}
      {loading && (
        <div style={{ color: "#64748b", fontSize: 13, padding: "8px 0" }}>
          Thinking… ⏳
        </div>
      )}

      {/* Error */}
      {error && (
        <div style={{ background: "#7f1d1d22", border: "1px solid #ef444455", borderRadius: 8, padding: "12px 16px", color: "#fca5a5", fontSize: 13 }}>
          ⚠️ {error}
        </div>
      )}

      {/* Result */}
      {result && !loading && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {/* Answer */}
          <div style={{
            background: "#1e293b",
            border: "1px solid #334155",
            borderRadius: 10,
            padding: "14px 16px",
          }}>
            <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6, textTransform: "uppercase", letterSpacing: 1 }}>
              {result.type === "rag" ? "📚 KB Answer" : result.type === "blocked" ? "🚫 Blocked" : "💬 Answer"}
            </div>
            <div style={{ fontSize: 14, lineHeight: 1.6, color: "#f1f5f9" }}>
              {result.answer ?? "No answer returned."}
            </div>
            {result.source && (
              <div style={{ marginTop: 8, fontSize: 11, color: "#6366f1" }}>
                📄 Source: {result.source}
              </div>
            )}
          </div>

          {/* SQL */}
          {result.sql && (
            <div style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 8, padding: "10px 14px" }}>
              <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6, textTransform: "uppercase", letterSpacing: 1 }}>
                🔍 SQL Ran
              </div>
              <pre style={{ fontSize: 11, color: "#7dd3fc", overflowX: "auto", lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
                {result.sql}
              </pre>
            </div>
          )}

          {/* Rows */}
          {result.rows && result.rows.length > 0 && (
            <div style={{ overflowX: "auto" }}>
              <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6, textTransform: "uppercase", letterSpacing: 1 }}>
                📊 Rows ({result.rows.length})
              </div>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid #334155" }}>
                    {Object.keys(result.rows[0]).map(k => (
                      <th key={k} style={{ textAlign: "left", padding: "6px 10px", color: "#64748b", fontWeight: 600, whiteSpace: "nowrap" }}>
                        {k}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.slice(0, 20).map((row, i) => (
                    <tr key={i} style={{ borderBottom: "1px solid #1e293b" }}>
                      {Object.values(row).map((v, j) => (
                        <td key={j} style={{ padding: "6px 10px", color: "#cbd5e1" }}>
                          {String(v ?? "")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
