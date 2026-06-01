import React, { useEffect, useState } from "react";
import { getBookings, type Booking } from "../api";

const STATUS_COLORS: Record<string, string> = {
  confirmed:              "#22c55e",
  cancelled:              "#f43f5e",
  no_show:                "#f97316",
  checked_out:            "#60a5fa",
  pending_confirmation:   "#eab308",
};

interface Props {
  propertyId: string;
}

export function BookingsList({ propertyId }: Props) {
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    getBookings(propertyId, 50)
      .then(res => { setBookings(res.data.items); setError(null); })
      .catch(() => setError("Could not load bookings."))
      .finally(() => setLoading(false));
  }, [propertyId]);

  if (loading) return <Skeleton />;
  if (error) return <ErrorBox msg={error} />;
  if (!bookings.length) return <Empty msg="No bookings found." />;

  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: "1px solid #334155", color: "#64748b" }}>
            {["Booking ID", "Type", "Check-in", "Check-out", "Status", "Amount", "Source"].map(h => (
              <th key={h} style={{ textAlign: "left", padding: "8px 10px", fontWeight: 600, whiteSpace: "nowrap" }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {bookings.map(b => {
            const color = STATUS_COLORS[b.status] ?? "#94a3b8";
            return (
              <tr key={b.booking_id} style={{ borderBottom: "1px solid #1e293b" }}>
                <td style={{ padding: "8px 10px", color: "#94a3b8", fontFamily: "monospace", fontSize: 11 }}>
                  {b.booking_id}
                </td>
                <td style={{ padding: "8px 10px" }}>{b.room_type}</td>
                <td style={{ padding: "8px 10px" }}>{b.checkin}</td>
                <td style={{ padding: "8px 10px" }}>{b.checkout}</td>
                <td style={{ padding: "8px 10px" }}>
                  <span style={{
                    background: color + "22", color, border: `1px solid ${color}55`,
                    borderRadius: 4, padding: "2px 7px", fontSize: 11, fontWeight: 600,
                  }}>
                    {b.status}
                  </span>
                </td>
                <td style={{ padding: "8px 10px" }}>₹{b.amount_inr?.toLocaleString()}</td>
                <td style={{ padding: "8px 10px", color: "#94a3b8" }}>{b.source}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Skeleton() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {[1, 2, 3, 4].map(i => (
        <div key={i} style={{ height: 40, background: "#1e293b", borderRadius: 6, opacity: 0.5 }} />
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
    <div style={{ color: "#475569", textAlign: "center", padding: "32px 0", fontSize: 14 }}>{msg}</div>
  );
}
