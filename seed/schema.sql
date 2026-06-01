-- Multi-tenant HMS schema. Every table carries property_id; scope ALL queries by it server-side.
CREATE TABLE IF NOT EXISTS properties (
  property_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  city TEXT,
  total_rooms INT
);
CREATE TABLE IF NOT EXISTS rooms (
  room_id TEXT PRIMARY KEY,
  property_id TEXT REFERENCES properties(property_id),
  room_type TEXT,            -- standard | deluxe | suite
  capacity INT
);
CREATE TABLE IF NOT EXISTS rates (
  rate_id TEXT PRIMARY KEY,
  property_id TEXT REFERENCES properties(property_id),
  room_type TEXT,
  date DATE,
  price_inr INT
);
CREATE TABLE IF NOT EXISTS bookings (
  booking_id TEXT PRIMARY KEY,
  property_id TEXT REFERENCES properties(property_id),
  room_type TEXT,
  checkin DATE,
  checkout DATE,
  status TEXT,               -- confirmed | cancelled | no_show | checked_out
  amount_inr INT,
  source TEXT                -- direct | mmt | booking_com | agoda
);
