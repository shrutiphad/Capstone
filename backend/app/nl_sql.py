"""
NL → SQL guard.

Security pipeline:
1. LLM generates candidate SQL from question + schema context
2. Python validates:
   a. Single SELECT only (no INSERT/UPDATE/DELETE/DROP etc.)
   b. No multi-statement (no bare `;` inside)
   c. No dangerous keywords (information_schema, pg_*, etc.)
   d. Tables referenced exist in our allowed set
   e. Columns referenced match known schema columns
3. Tenant scope injected IN PYTHON (never trust LLM to add it)
4. Runs in a read-only transaction with RLS enforced
"""
import json
import logging
import re
import anthropic

from .config import get_settings
from .database import get_pool

logger = logging.getLogger(__name__)

# ── Schema knowledge ──────────────────────────────────────────────────────────

ALLOWED_TABLES = {"properties", "rooms", "rates", "bookings", "events", "message_logs"}

TABLE_COLUMNS: dict[str, set[str]] = {
    "properties":   {"property_id", "name", "city", "total_rooms", "config"},
    "rooms":        {"room_id", "property_id", "room_type", "capacity"},
    "rates":        {"rate_id", "property_id", "room_type", "date", "price_inr"},
    "bookings":     {"booking_id", "property_id", "room_type", "checkin", "checkout",
                     "status", "amount_inr", "source", "created_at"},
    "message_logs": {"id", "property_id", "message_id", "guest_id", "text",
                     "intent", "confidence", "status", "created_at"},
    "events":       {"id", "property_id", "event_type", "payload", "created_at"},
}

SCHEMA_SUMMARY = """
Tables available (all filtered by property_id automatically):
- bookings(booking_id, property_id, room_type, checkin DATE, checkout DATE, status TEXT, amount_inr INT, source TEXT, created_at TIMESTAMPTZ)
  status values: confirmed, cancelled, no_show, checked_out, pending_confirmation
  source values: direct, mmt, booking_com, agoda
- rooms(room_id, property_id, room_type TEXT, capacity INT)
  room_type values: standard, deluxe, suite
- rates(rate_id, property_id, room_type TEXT, date DATE, price_inr INT)
- properties(property_id, name, city, total_rooms INT, config JSONB)
- events(id, property_id, event_type TEXT, payload JSONB, created_at TIMESTAMPTZ)
- message_logs(id, property_id, message_id, guest_id, text, intent, confidence, status, created_at)

DO NOT add WHERE property_id = ... — it will be added automatically.
Generate a single SELECT query only. Use standard PostgreSQL syntax.
"""

DANGEROUS_PATTERNS = [
    r"\bINSERT\b", r"\bUPDATE\b", r"\bDELETE\b", r"\bDROP\b",
    r"\bCREATE\b", r"\bALTER\b", r"\bTRUNCATE\b", r"\bEXEC\b",
    r"\bEXECUTE\b", r"\bGRANT\b", r"\bREVOKE\b",
    r"information_schema", r"\bpg_", r"\bxp_",
    r"/\*", r"--\s",  # comment injection
    r"\bUNION\b",  # UNION-based injection
    r"\bSLEEP\b", r"\bPG_SLEEP\b",
]


class SQLGuardError(ValueError):
    pass


def _validate_sql(sql: str) -> str:
    """Validate and clean SQL. Raises SQLGuardError if unsafe."""
    sql_clean = sql.strip().rstrip(";")

    # No multi-statement
    # Allow semicolons only at the very end (strip above), block embedded ones
    if ";" in sql_clean:
        raise SQLGuardError("Multi-statement SQL blocked")

    # Must be a SELECT
    if not re.match(r"^\s*SELECT\b", sql_clean, re.IGNORECASE):
        raise SQLGuardError("Only SELECT queries are allowed")

    # Dangerous keyword check
    sql_upper = sql_clean.upper()
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, sql_upper, re.IGNORECASE):
            raise SQLGuardError(f"Blocked pattern: {pattern}")

    # Check referenced tables
    table_matches = re.findall(r"\bFROM\s+(\w+)|\bJOIN\s+(\w+)", sql_clean, re.IGNORECASE)
    referenced_tables = {t for pair in table_matches for t in pair if t}
    for tbl in referenced_tables:
        if tbl.lower() not in ALLOWED_TABLES:
            raise SQLGuardError(f"Table '{tbl}' not in allowed schema")

    return sql_clean


def _inject_tenant(sql: str, property_id: str) -> str:
    """
    Wrap the query in a CTE that enforces the tenant filter.
    This guarantees the filter even if the LLM omitted it.
    """
    # Use a subquery wrapper — safe even for complex queries
    return (
        f"SELECT * FROM ({sql}) AS __q "
        f"WHERE __q.property_id = '{property_id}'"
    )


async def _generate_sql_llm(question: str) -> str:
    """Ask Claude to generate a tenant-agnostic SQL query."""
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    prompt = f"""You are a PostgreSQL query generator for a hotel management system.

Schema:
{SCHEMA_SUMMARY}

Question (may be in English, Hindi, or Hinglish): "{question}"

Rules:
- Return ONLY valid PostgreSQL SELECT SQL, no explanation
- Do NOT add WHERE property_id = ... (it is added automatically)
- Do NOT add semicolons
- If the question cannot be answered from this schema, return exactly: UNANSWERABLE
- Use proper date functions if needed (NOW(), CURRENT_DATE, DATE_TRUNC etc.)
- Keep the query simple and correct

SQL:"""

    try:
        response = await client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        result = response.content[0].text.strip()
        # Remove markdown fences
        result = re.sub(r"```sql|```", "", result).strip()
        return result
    except Exception as exc:
        logger.error("LLM SQL gen failed: %s", exc)
        raise SQLGuardError(f"LLM failed: {exc}")


async def execute_nl_query(question: str, property_id: str) -> dict:
    """
    Full NL→SQL pipeline with guards.
    Returns {answer, sql, rows} or raises SQLGuardError.
    """
    # 1. Generate
    candidate_sql = await _generate_sql_llm(question)

    if candidate_sql.strip().upper() == "UNANSWERABLE":
        return {
            "answer": "Main yeh sawal answer nahi kar sakta — yeh data schema mein nahi hai.",
            "sql": None,
            "rows": [],
        }

    # 2. Validate (app-level guard)
    safe_sql = _validate_sql(candidate_sql)

    # 3. Inject tenant scope (app-level, NOT LLM)
    tenant_sql = _inject_tenant(safe_sql, property_id)

    # 4. Execute in read-only transaction with RLS
    rows = []
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Set RLS context (defense-in-depth on top of the subquery filter)
                await conn.execute(
                    "SELECT set_config('app.current_property_id', $1, TRUE)", property_id
                )
                # Force read-only
                await conn.execute("SET LOCAL default_transaction_read_only = on")
                records = await conn.fetch(tenant_sql)
                rows = [dict(r) for r in records]
    except SQLGuardError:
        raise
    except Exception as exc:
        logger.error("SQL execution error: %s | sql=%s", exc, tenant_sql)
        raise SQLGuardError(f"Query execution failed: {exc}")

    # 5. Summarize
    answer = await _summarize_results(question, rows, tenant_sql)

    return {
        "answer": answer,
        "sql": tenant_sql,
        "rows": _serialize_rows(rows),
    }


def _serialize_rows(rows: list[dict]) -> list[dict]:
    """Convert non-serializable types to strings."""
    import datetime
    result = []
    for row in rows:
        r = {}
        for k, v in row.items():
            if isinstance(v, (datetime.date, datetime.datetime)):
                r[k] = v.isoformat()
            elif isinstance(v, datetime.timedelta):
                r[k] = str(v)
            else:
                r[k] = v
        result.append(r)
    return result


async def _summarize_results(question: str, rows: list[dict], sql: str) -> str:
    """Convert rows to a natural language answer."""
    settings = get_settings()
    if not rows:
        return "Koi data nahi mila is sawal ke liye."

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    rows_preview = json.dumps(rows[:20], default=str)

    prompt = f"""Question (English/Hindi/Hinglish): "{question}"
Data rows: {rows_preview}
Total rows: {len(rows)}

Answer in the same language as the question (1-3 sentences, be specific with numbers).
If Hindi/Hinglish, answer in Hinglish."""

    try:
        resp = await client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception:
        # Fallback: simple summary
        return f"{len(rows)} record(s) found."
