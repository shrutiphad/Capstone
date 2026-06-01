import React, { useEffect, useState } from "react";
import { EventsFeed } from "./components/EventsFeed";
import { BookingsList } from "./components/BookingsList";
import { AskAssistant } from "./components/AskAssistant";
import { getHealth } from "./api";

// Known properties from seed — can also be fetched from /properties endpoint
const PROPERTIES = [
  { id: "prop_001", name: "Hotel Sunrise Delhi" },
  { id: "prop_002", name: "Hotel Pearl Mumbai" },
];

type Tab = "events" | "bookings" | "ask";

export default function App() {
  const [propertyId, setPropertyId] = useState(PROPERTIES[0].id);
  const [activeTab, setActiveTab] = useState<Tab>("events");
  const [backendOk, setBackendOk] = useState<boolean | null>(null);

  useEffect(() => {
    getHealth()
      .then(() => setBackendOk(true))
      .catch(() => setBackendOk(false));
  }, []);

  const tabs: { id: Tab; label: string }[] = [
    { id: "events", label: "📡 Events Feed" },
    { id: "bookings", label: "🏨 Bookings" },
    { id: "ask", label: "🤖 Ask Assistant" },
  ];

  return (
    <div style={{ minHeight: "100vh", background: "#0f172a" }}>
      {/* Header */}
      <header style={{
        background: "#1e293b",
        borderBottom: "1px solid #334155",
        padding: "0 16px",
        position: "sticky",
        top: 0,
        zIndex: 10,
      }}>
        <div style={{ maxWidth: 900, margin: "0 auto", display: "flex", alignItems: "center", justifyContent: "space-between", height: 56 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 20 }}>🏩</span>
            <span style={{ fontWeight: 700, fontSize: 16, color: "#f1f5f9" }}>Owner Console</span>
            {backendOk === true && (
              <span style={{ background: "#14532d33", border: "1px solid #22c55e55", color: "#22c55e", borderRadius: 4, fontSize: 10, padding: "2px 6px" }}>
                LIVE
              </span>
            )}
            {backendOk === false && (
              <span style={{ background: "#7f1d1d33", border: "1px solid #ef444455", color: "#f87171", borderRadius: 4, fontSize: 10, padding: "2px 6px" }}>
                OFFLINE
              </span>
            )}
          </div>

          {/* Property switcher */}
          <select
            value={propertyId}
            onChange={e => setPropertyId(e.target.value)}
            style={{
              background: "#0f172a",
              border: "1px solid #334155",
              color: "#f1f5f9",
              borderRadius: 6,
              padding: "6px 10px",
              fontSize: 13,
              cursor: "pointer",
            }}
          >
            {PROPERTIES.map(p => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>
      </header>

      {/* Tabs */}
      <div style={{ background: "#1e293b", borderBottom: "1px solid #334155" }}>
        <div style={{ maxWidth: 900, margin: "0 auto", display: "flex", gap: 2, padding: "0 16px" }}>
          {tabs.map(t => (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              style={{
                background: activeTab === t.id ? "#0f172a" : "transparent",
                color: activeTab === t.id ? "#f1f5f9" : "#64748b",
                border: "none",
                borderTop: activeTab === t.id ? "2px solid #6366f1" : "2px solid transparent",
                padding: "12px 16px",
                cursor: "pointer",
                fontSize: 13,
                fontWeight: activeTab === t.id ? 600 : 400,
                transition: "all 0.15s",
              }}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <main style={{ maxWidth: 900, margin: "0 auto", padding: "20px 16px" }}>
        {/* Property badge */}
        <div style={{ marginBottom: 16, display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 11, color: "#475569", textTransform: "uppercase", letterSpacing: 1 }}>Property:</span>
          <span style={{ fontSize: 13, fontWeight: 600, color: "#94a3b8", fontFamily: "monospace" }}>{propertyId}</span>
          <span style={{ fontSize: 12, color: "#64748b" }}>
            — {PROPERTIES.find(p => p.id === propertyId)?.name}
          </span>
        </div>

        {activeTab === "events" && (
          <section>
            <SectionHeader title="Live Events Feed" subtitle="Auto-refreshes every 8 seconds" />
            <EventsFeed propertyId={propertyId} />
          </section>
        )}

        {activeTab === "bookings" && (
          <section>
            <SectionHeader title="Bookings" subtitle="Tenant-scoped, most recent first" />
            <BookingsList propertyId={propertyId} />
          </section>
        )}

        {activeTab === "ask" && (
          <section>
            <SectionHeader
              title="Ask the Data Assistant"
              subtitle="Data questions → NL→SQL | Product questions → Knowledge Base"
            />
            <AskAssistant propertyId={propertyId} />
          </section>
        )}
      </main>
    </div>
  );
}

function SectionHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <h2 style={{ fontSize: 18, fontWeight: 700, color: "#f1f5f9" }}>{title}</h2>
      <p style={{ fontSize: 12, color: "#475569", marginTop: 3 }}>{subtitle}</p>
    </div>
  );
}
