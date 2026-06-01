import axios from "axios";

const BASE = import.meta.env.VITE_API_URL || "";

const api = axios.create({ baseURL: BASE, timeout: 15000 });

export interface Event {
  id: number;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface Booking {
  booking_id: string;
  room_type: string;
  checkin: string;
  checkout: string;
  status: string;
  amount_inr: number;
  source: string;
  created_at: string | null;
}

export interface AskResponse {
  answer: string | null;
  sql: string | null;
  rows: Record<string, unknown>[];
  source: string | null;
  type: string;
}

export const getEvents = (propertyId: string, limit = 50) =>
  api.get<{ events: Event[] }>("/events", { params: { property_id: propertyId, limit } });

export const getBookings = (propertyId: string, limit = 50) =>
  api.get<{ items: Booking[] }>("/bookings", { params: { property_id: propertyId, limit } });

export const postAsk = (propertyId: string, question: string) =>
  api.post<AskResponse>("/ask", { property_id: propertyId, question });

export const getHealth = () => api.get("/health");
