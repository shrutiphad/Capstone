"""
Database layer.
- asyncpg connection pool
- Tenant-scoped query helper (enforces RLS via set_config)
- Schema + RLS migration helpers
"""

import asyncpg
import logging
from typing import Any

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

# Tables whose property_id we allow in queries
ALLOWED_TABLES = {"properties", "rooms", "rates", "bookings", "events", "message_logs"}

# Full schema with RLS
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS properties (
    property_id TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    city        TEXT,
    total_rooms INT,
    config      JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS rooms (
    room_id     TEXT PRIMARY KEY,
    property_id TEXT REFERENCES properties(property_id) ON DELETE CASCADE,
    room_type   TEXT,
    capacity    INT
);

CREATE TABLE IF NOT EXISTS rates (
    rate_id     TEXT PRIMARY KEY,
    property_id TEXT REFERENCES properties(property_id) ON DELETE CASCADE,
    room_type   TEXT,
    date        DATE,
    price_inr   INT
);

CREATE TABLE IF NOT EXISTS bookings (
    booking_id  TEXT PRIMARY KEY,
    property_id TEXT REFERENCES properties(property_id) ON DELETE CASCADE,
    room_type   TEXT,
    checkin     DATE,
    checkout    DATE,
    status      TEXT,
    amount_inr  INT,
    source      TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS message_logs (
    id          BIGSERIAL PRIMARY KEY,
    property_id TEXT REFERENCES properties(property_id) ON DELETE CASCADE,
    message_id  TEXT UNIQUE NOT NULL,
    guest_id    TEXT,
    text        TEXT,
    intent      TEXT,
    confidence  FLOAT,
    status      TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS events (
    id          BIGSERIAL PRIMARY KEY,
    property_id TEXT REFERENCES properties(property_id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,
    payload     JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- RLS
ALTER TABLE properties    ENABLE ROW LEVEL SECURITY;
ALTER TABLE rooms         ENABLE ROW LEVEL SECURITY;
ALTER TABLE rates         ENABLE ROW LEVEL SECURITY;
ALTER TABLE bookings      ENABLE ROW LEVEL SECURITY;
ALTER TABLE message_logs  ENABLE ROW LEVEL SECURITY;
ALTER TABLE events        ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  -- properties
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='properties' AND policyname='rls_properties') THEN
    CREATE POLICY rls_properties ON properties
      USING (property_id = current_setting('app.current_property_id', TRUE));
  END IF;
  -- rooms
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='rooms' AND policyname='rls_rooms') THEN
    CREATE POLICY rls_rooms ON rooms
      USING (property_id = current_setting('app.current_property_id', TRUE));
  END IF;
  -- rates
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='rates' AND policyname='rls_rates') THEN
    CREATE POLICY rls_rates ON rates
      USING (property_id = current_setting('app.current_property_id', TRUE));
  END IF;
  -- bookings
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='bookings' AND policyname='rls_bookings') THEN
    CREATE POLICY rls_bookings ON bookings
      USING (property_id = current_setting('app.current_property_id', TRUE));
  END IF;
  -- message_logs
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='message_logs' AND policyname='rls_message_logs') THEN
    CREATE POLICY rls_message_logs ON message_logs
      USING (property_id = current_setting('app.current_property_id', TRUE));
  END IF;
  -- events
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='events' AND policyname='rls_events') THEN
    CREATE POLICY rls_events ON events
      USING (property_id = current_setting('app.current_property_id', TRUE));
  END IF;
END $$;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_bookings_property ON bookings(property_id);
CREATE INDEX IF NOT EXISTS idx_events_property ON events(property_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_message_logs_property ON message_logs(property_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_message_logs_msgid ON message_logs(message_id);
"""


async def init_pool(database_url: str) -> None:
    global _pool
    _pool = await asyncpg.create_pool(database_url, min_size=2, max_size=10)
    async with _pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
    logger.info("Database pool initialised")


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialised")
    return _pool


# ── Tenant-scoped execution ─────────────────────────────────────────────────

async def tenant_fetch(
    property_id: str, query: str, *args: Any
) -> list[asyncpg.Record]:
    """Run a SELECT inside a transaction with RLS set for this tenant."""
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.current_property_id', $1, TRUE)", property_id
            )
            return await conn.fetch(query, *args)


async def tenant_execute(
    property_id: str, query: str, *args: Any
) -> str:
    """Run a write inside a transaction with RLS set for this tenant."""
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.current_property_id', $1, TRUE)", property_id
            )
            return await conn.execute(query, *args)


async def admin_fetch(query: str, *args: Any) -> list[asyncpg.Record]:
    """Bypass RLS (for seeding/health checks). No property_id scope."""
    async with get_pool().acquire() as conn:
        return await conn.fetch(query, *args)


async def admin_execute(query: str, *args: Any) -> str:
    async with get_pool().acquire() as conn:
        return await conn.execute(query, *args)
