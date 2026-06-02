"""
NL→SQL guard.

Security pipeline:
1. LLM generates candidate SQL (no tenant filter — we add it)
2. Python validates:
   a. Single SELECT only
   b. No multi-statement (embedded semicolons)
   c. No dangerous keywords (INSERT/UPDATE/DELETE/DROP/UNION/information_schema/pg_*)
   d. Tables referenced exist in our allowed set
3. Tenant scope enforced IN PYTHON via RLS set_config (never trust LLM)
4. Runs in a read-only transaction


"""
import json
import logging
import re
import os
import asyncio
from groq import Groq

from .config import get_settings
from .database import get_pool

logger = logging.getLogger(__name__)

# ── Schema knowledge ──────────────────────────────────────────────────────────

ALLOWED_TABLES = {"properties", "rooms", "rates", "bookings", "events", "message_logs"}

SCHEMA_SUMMARY = """
Tables (all automatically filtered to the current property — DO NOT add WHERE property_id):
- bookings(booking_id TEXT, property_id TEXT, room_type TEXT, checkin DATE, checkout DATE,
           status TEXT, amount_inr INT, source TEXT, created_at TIMESTAMPTZ)
  status: confirmed | cancelled | no_show | checked_out
  source: direct | mmt | booking_com | agoda
  room_type: standard | deluxe | suite
- rooms(room_id TEXT, property_id TEXT, room_type TEXT, capacity INT)
- rates(rate_id TEXT, property_id TEXT, room_type TEXT, date DATE, price_inr INT)
- properties(property_id TEXT, name TEXT, city TEXT, total_rooms INT, config JSONB)
- events(id BIGINT, property_id TEXT, event_type TEXT, payload JSONB, created_at TIMESTAMPTZ)
- message_logs(id BIGINT, property_id TEXT, message_id TEXT, guest_id TEXT, text TEXT,
               intent TEXT, confidence FLOAT, status TEXT, created_at TIMESTAMPTZ)

Rules:
- Generate a single SELECT only. No semicolons. No INSERT/UPDATE/DELETE/DROP.
- Do NOT add WHERE property_id = ... (tenant filter is added automatically by the system).
- If the question cannot be answered from this schema, return exactly: UNANSWERABLE
- Use standard PostgreSQL syntax.
"""

DANGEROUS_PATTERNS = [
    r"\bINSERT\b", r"\bUPDATE\b", r"\bDELETE\b", r"\bDROP\b",
    r"\bCREATE\b", r"\bALTER\b", r"\bTRUNCATE\b",
    r"\bEXEC\b", r"\bEXECUTE\b", r"\bGRANT\b", r"\bREVOKE\b",
    r"information_schema", r"\bpg_",
    r"/\*",           # block comment injection
    r"--",            # line comment injection
    r"\bUNION\b",     # UNION-based data exfiltration
    r"\bSLEEP\b", r"\bPG_SLEEP\b",
]


class SQLGuardError(ValueError):
    pass


def _validate_sql(sql: str) -> str:
    """Validate SQL string. Raises SQLGuardError if unsafe. Returns clean SQL."""
    sql_clean = sql.strip().rstrip(";")

    # No embedded semicolons (multi-statement)
    if ";" in sql_clean:
        raise SQLGuardError("Multi-statement SQL blocked")

    # Must start with SELECT
    if not re.match(r"^\s*SELECT\b", sql_clean, re.IGNORECASE):
        raise SQLGuardError("Only SELECT queries are allowed")

    # Dangerous keyword check (case-insensitive)
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, sql_clean, re.IGNORECASE):
            raise SQLGuardError(f"Blocked pattern detected: {pattern}")

    # Validate referenced tables
    table_refs = re.findall(r"\bFROM\s+(\w+)|\bJOIN\s+(\w+)", sql_clean, re.IGNORECASE)
    referenced = {t.lower() for pair in table_refs for t in pair if t}
    for tbl in referenced:
        if tbl not in ALLOWED_TABLES:
            raise SQLGuardError(f"Table '{tbl}' not in allowed schema")

    return sql_clean


async def _generate_sql_llm(question: str) -> str:
    """Ask Groq LLM to generate a tenant-agnostic SQL query."""
    settings = get_settings()

    prompt = f"""You are a PostgreSQL query generator for a hotel management system.

Schema:
{SCHEMA_SUMMARY}

Question (may be in English, Hindi, or Hinglish): "{question}"

Return ONLY the SQL query — no explanation, no markdown fences, no semicolons.
If unanswerable from this schema, return exactly: UNANSWERABLE"""

    try:
        client = Groq(api_key=settings.GROQ_API_KEY)
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
        )
        result = response.choices[0].message.content.strip()
        result = re.sub(r"```sql|```", "", result).strip()
        return result
    except Exception as exc:
        logger.error("LLM SQL gen failed: %s", exc)
        raise SQLGuardError(f"LLM failed to generate SQL: {exc}")


async def execute_nl_query(question: str, property_id: str) -> dict:
    """
    Full NL→SQL pipeline with guards.
    Tenant scope enforced via RLS (set_config) — not via LLM.
    Returns {answer, sql, rows}.
    """
    # 1. Generate SQL via LLM
    candidate_sql = await _generate_sql_llm(question)

    if candidate_sql.strip().upper() == "UNANSWERABLE":
        return {
            "answer": "Yeh sawal is data se answer nahi ho sakta. Schema mein yeh information nahi hai.",
            "sql": None,
            "rows": [],
        }

    # 2. Validate (Python guard — no trust in LLM output)
    safe_sql = _validate_sql(candidate_sql)

    # 3. Execute in read-only transaction with RLS enforced
    # Tenant scope = set_config → RLS policy filters rows automatically
    # This is the correct defense: DB-level, not app-code WHERE clause
    rows = []
    executed_sql = safe_sql
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Set RLS context — this is the tenant enforcement
                await conn.execute(
                    "SELECT set_config('app.current_property_id', $1, TRUE)", property_id
                )
                # Force read-only for this transaction
                await conn.execute("SET LOCAL default_transaction_read_only = on")
                records = await conn.fetch(safe_sql)
                rows = [dict(r) for r in records]
    except SQLGuardError:
        raise
    except Exception as exc:
        logger.error("SQL execution error: %s | sql=%s", exc, safe_sql)
        raise SQLGuardError(f"Query execution failed: {exc}")

    # 4. Natural language summary
    answer = await _summarize_results(question, rows, executed_sql)

    return {
        "answer": answer,
        "sql": executed_sql,
        "rows": _serialize_rows(rows),
    }


def _serialize_rows(rows: list[dict]) -> list[dict]:
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
    """Convert rows to a natural language answer in the question's language."""
    settings = get_settings()
    if not rows:
        return "Koi data nahi mila is sawal ke liye."

    rows_preview = json.dumps(rows[:20], default=str)
    prompt = f"""Question (English/Hindi/Hinglish): "{question}"
Data rows returned: {rows_preview}
Total rows: {len(rows)}

Answer in the SAME language as the question (1-3 sentences, be specific with numbers).
If Hindi/Hinglish question, answer in Hinglish."""

    try:
        client = Groq(api_key=settings.GROQ_API_KEY)
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return f"{len(rows)} record(s) found."