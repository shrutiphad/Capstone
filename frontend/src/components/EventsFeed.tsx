import React, { useEffect, useRef, useState } from "react";
import { getEvents, type Event } from "../api";

const BADGE_COLORS: Record<string, string> = {
  booking_created:       "#22c55e",
  cancellation_requested:"#f97316",
  human_handoff:         "#eab308",
  faq_handled:           "#60a5fa",
  complaint_logged:      "#f43f5e",
  wakeup_scheduled:      "#a78bfa",
  ota_push_ok:           "#34d399",
  ota_push_failed:       "#ef4444",
};

function Badge({ type }: { type: string }) {
  const color = BADGE_COLORS[type] ?? "#94a3b8";
  return (
    <span style={{
      background: color + "22",
      color,
      border: `1px solid ${color}55`,
      borderRadius: 4,
      padding: "2px 8px",
      fontSize: 11,
      fontWeight: 600,
      whiteSpace: "nowrap",
    }}>
      {type.replace(/_/g, " ")}
    </span>
  );
}

interface Props {
  propertyId: string;
}

export function EventsFeed({ propertyId }: Props) {
  const [events, setEvents] = useState<Event[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchEvents = async () => {
    try {
      const res = await getEvents(propertyId, 30);
      setEvents(res.data.events);
      setError(null);
    } catch (e: unknown) {
      setError("Could not load events. Retrying…");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setLoading(true);
    fetchEvents();
    intervalRef.current = setInterval(fetchEvents, 8000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [propertyId]);

  if (loading) return <Skeleton />;
  if (error) return <ErrorBox msg={error} />;
  if (!events.length) return <Empty msg="No events yet. Send a message to get started." />;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {events.map((ev) => (
        <div key={ev.id} style={{
          background: "#1e293b",
          border: "1px solid #334155",
          borderRadius: 8,
          padding: "10px 14px",
          display: "flex",
          flexDirection: "column",
          gap: 4,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 6 }}>
            <Badge type={ev.event_type} />
            <span style={{ color: "#64748b", fontSize: 11 }}>
              {new Date(ev.created_at).toLocaleTimeString()}
            </span>
          </div>
          {ev.payload && Object.keys(ev.payload).length > 0 && (
            <pre style={{
              fontSize: 11,
              color: "#94a3b8",
              background: "#0f172a",
              borderRadius: 4,
              padding: "4px 8px",
              overflowX: "auto",
              marginTop: 2,
            }}>
              {JSON.stringify(ev.payload, null, 2)}
            </pre>
          )}
        </div>
      ))}
    </div>
  );
}

function Skeleton() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {[1, 2, 3].map(i => (
        <div key={i} style={{
          height: 56,
          background: "#1e293b",
          borderRadius: 8,
          animation: "pulse 1.5s infinite",
          opacity: 0.6,
        }} />
      ))}
    </div>
  );
}

function ErrorBox({ msg }: { msg: string }) {
  return (
    <div style={{ background: "#7f1d1d22", border: "1px solid #ef444455", borderRadius: 8, padding: "12px 16px", color: "#fca5a5" }}>
      ⚠️ {msg}
    </div>
  );
}

function Empty({ msg }: { msg: string }) {
  return (
    <div style={{ color: "#475569", textAlign: "center", padding: "32px 0", fontSize: 14 }}>
      {msg}
    </div>
  );
}
