"""
Database layer — asyncpg pool + RLS helpers.

Schema extends starter schema.sql with:
  - config JSONB on properties (for language/custom_faqs)
  - created_at on bookings
  - message_logs table (idempotency)
  - events table (lifecycle feed)
  - RLS policies on all tables
"""
import asyncpg
import logging
from typing import Any

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

ALLOWED_TABLES = {"properties", "rooms", "rates", "bookings", "events", "message_logs"}

# Schema migration — extends starter schema.sql safely with IF NOT EXISTS
MIGRATION_SQL = """
-- Extend properties with config if not present
ALTER TABLE properties ADD COLUMN IF NOT EXISTS city TEXT;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS total_rooms INT;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS config JSONB DEFAULT '{}';

-- Extend bookings with created_at if not present
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

-- Message logs (idempotency + classification record)
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

-- Events (lifecycle feed)
CREATE TABLE IF NOT EXISTS events (
    id          BIGSERIAL PRIMARY KEY,
    property_id TEXT REFERENCES properties(property_id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,
    payload     JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_bookings_property  ON bookings(property_id);
CREATE INDEX IF NOT EXISTS idx_events_property    ON events(property_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_msglogs_property   ON message_logs(property_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_msglogs_msgid ON message_logs(message_id);

-- RLS
ALTER TABLE properties    ENABLE ROW LEVEL SECURITY;
ALTER TABLE rooms         ENABLE ROW LEVEL SECURITY;
ALTER TABLE rates         ENABLE ROW LEVEL SECURITY;
ALTER TABLE bookings      ENABLE ROW LEVEL SECURITY;
ALTER TABLE message_logs  ENABLE ROW LEVEL SECURITY;
ALTER TABLE events        ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='properties' AND policyname='rls_properties') THEN
    CREATE POLICY rls_properties ON properties
      USING (property_id = current_setting('app.current_property_id', TRUE));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='rooms' AND policyname='rls_rooms') THEN
    CREATE POLICY rls_rooms ON rooms
      USING (property_id = current_setting('app.current_property_id', TRUE));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='rates' AND policyname='rls_rates') THEN
    CREATE POLICY rls_rates ON rates
      USING (property_id = current_setting('app.current_property_id', TRUE));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='bookings' AND policyname='rls_bookings') THEN
    CREATE POLICY rls_bookings ON bookings
      USING (property_id = current_setting('app.current_property_id', TRUE));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='message_logs' AND policyname='rls_message_logs') THEN
    CREATE POLICY rls_message_logs ON message_logs
      USING (property_id = current_setting('app.current_property_id', TRUE));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='events' AND policyname='rls_events') THEN
    CREATE POLICY rls_events ON events
      USING (property_id = current_setting('app.current_property_id', TRUE));
  END IF;
END $$;
"""


async def init_pool(database_url: str) -> None:
    global _pool
  
    
    ssl_setting = "require" if "supabase.co" in database_url else "disable"
    _pool = await asyncpg.create_pool(database_url, min_size=2, max_size=10, ssl=ssl_setting)

    from pathlib import Path
    schema_file = Path(__file__).parent.parent / "seed" / "schema.sql"
    if schema_file.exists():
        schema_sql = schema_file.read_text()
        async with _pool.acquire() as conn:
            await conn.execute(schema_sql)
    async with _pool.acquire() as conn:
        await conn.execute(MIGRATION_SQL)
    logger.info("Database pool initialised + schema migrated")


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialised")
    return _pool


# ── Tenant-scoped helpers ────────────────────────────────────────────────────

async def tenant_fetch(property_id: str, query: str, *args: Any) -> list[asyncpg.Record]:
    """SELECT inside a transaction with RLS set for this tenant."""
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.current_property_id', $1, TRUE)", property_id
            )
            return await conn.fetch(query, *args)


async def tenant_execute(property_id: str, query: str, *args: Any) -> str:
    """Write inside a transaction with RLS set for this tenant."""
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.current_property_id', $1, TRUE)", property_id
            )
            return await conn.execute(query, *args)


async def admin_fetch(query: str, *args: Any) -> list[asyncpg.Record]:
    """Bypass RLS — for seeding/health checks only."""
    async with get_pool().acquire() as conn:
        return await conn.fetch(query, *args)


async def admin_execute(query: str, *args: Any) -> str:
    async with get_pool().acquire() as conn:
        return await conn.execute(query, *args)
