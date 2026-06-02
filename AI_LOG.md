# AI_LOG — Engineering Capstone

## Tools used
- Claude (Anthropic) — architecture design, code generation, SQL guard logic, test strategy
- GitHub Copilot — inline autocomplete during implementation

---

## Most useful prompts
- "Design a 2-stage intent classifier where stage 1 is rule-based (no LLM) and stage 2 calls an LLM only when confidence is low — return (intent, confidence)"
- "Write a Python SQL guard that blocks everything except a single SELECT: no semicolons, no INSERT/UPDATE/DELETE/DROP/UNION, no information_schema, no unknown tables. Raise SQLGuardError."
- "Given this hotel schema, write a FastAPI endpoint that enforces tenant isolation via PostgreSQL RLS using asyncpg set_config inside a transaction — not via WHERE clauses in app code."
- "Write pytest tests for all 15 seed messages from labeled_messages.json, including m14 which must not auto-cancel."

---

## Where AI was WRONG / gave broken output, and how you caught it

### 1. Inline side-effects (caught during design review)
First draft of `POST /message` called the booking workflow directly in the route handler — `await _handle_booking(...)` inline. This violates the spec: "side-effects via a QUEUE, not inline." Caught by re-reading the spec. Fixed: message handler only calls `await enqueue(...)` and returns immediately; worker runs in a background `asyncio.Task`.

### 2. Tenant scope via app-code WHERE clause (caught during spec review)
First draft of `nl_sql.py` used a subquery wrapper: `SELECT * FROM ({LLM_SQL}) AS __q WHERE __q.property_id = '{property_id}'`. This breaks aggregate queries — `SELECT COUNT(*)` has no `property_id` column in the outer result. Also, the spec says "RLS (not app-code)". Fixed: removed the subquery wrapper entirely. Tenant scope is enforced by `set_config('app.current_property_id', ...)` → RLS policy at the DB level. The Python guard is for injection/destructive query blocking, not for tenant filtering.

### 3. No idempotency → double-fires on replay (caught with test)
First draft had no `UNIQUE` constraint on `message_id` and no pre-check. Running the same message twice would create two booking rows and emit two events. Caught by writing `test_idempotency_replay`. Fixed: `message_logs.message_id UNIQUE` + check-before-act at the start of `/message`.

### 4. Auto-cancel on ambiguous message (caught with m14 test)
First draft used a single `CONFIDENCE_THRESHOLD=0.6` for all intents including cancellation. m14 ("umm maybe cancel or change, not sure yet") classified as `cancellation` with ~0.65 confidence and got auto-queued. This is the explicit HARD FAIL in the spec. Caught by writing `test_m14_ambiguous_must_not_auto_cancel`. Fixed: added `CANCEL_CONFIDENCE_THRESHOLD=0.75` — a higher bar specifically for cancellation. Anything below this threshold on a cancellation intent goes to `needs_confirmation`, not the cancellation workflow.

### 5. Pydantic v2 settings import (caught at startup)
AI generated `from pydantic import BaseSettings` — this only works in Pydantic v1. In v2 it's `from pydantic_settings import BaseSettings`. Caught when `uvicorn app.main:app` crashed with `ImportError`. Fixed: use `pydantic-settings==2.2.1`.

### 6. Mock OTA was rewritten incorrectly (caught by comparing to starter)
AI generated a different mock OTA with different failure rates and no `random.seed(7)`. The starter's `mock_ota_server.py` uses `random.seed(7)` for deterministic-ish grading and has `GET /rates` with pagination. Fixed: used the exact starter `mock_ota_server.py` verbatim.

### 7. properties.json has no `city` or `total_rooms` fields (caught by reading seed file)
Seed code tried to read `prop.get("city", "")` and `prop.get("total_rooms", 0)` from properties.json, but those fields don't exist there — they're in `data.sql`. Caused a silent mismatch where properties were seeded with empty city/0 rooms even though data.sql had the correct values in the rooms/rates tables. Fixed: seed.py reads only `property_id`, `name`, `language`, `custom_faqs` from properties.json.

---

## Design decisions

### Intent classifier — 2-stage (rules → LLM)
Stage 1 is keyword rules with no LLM call — P95 < 1ms. Stage 2 calls Claude Haiku only when rules give confidence < 0.6 or fire no keywords. This means high-volume obvious messages (most real traffic) never hit the API. Trade-off: rules require maintenance as language evolves. Would add a periodic accuracy test against a golden set to detect rule drift.

### Tenant isolation — RLS
Used PostgreSQL RLS (`set_config` + policy) rather than `WHERE property_id = $1` in every query. RLS is enforced at the DB engine level — it can't be bypassed by a bug in app code or an LLM-generated query that "forgets" the filter. Every `tenant_fetch` / `tenant_execute` call sets `app.current_property_id` inside a transaction before the query runs. Admin functions (`admin_fetch`, `admin_execute`) bypass RLS intentionally — used only for seeding and idempotency checks.

### Idempotency + queue
`message_logs.message_id UNIQUE` is the source of truth. On every `/message` request, we check for an existing row first (one DB read). If found, return the cached result — zero side-effects. The `asyncio.Queue` is in-process; acceptable for this scope. For 100 hotels, would switch to a durable broker (Redis Streams or BullMQ) so jobs survive restarts.

### NL→SQL guardrails
Two layers: (1) Python regex/keyword validator — blocks INSERT/UPDATE/DELETE/DROP/UNION/information_schema/pg_* before the query ever reaches Postgres. (2) RLS at DB level — even if a SELECT slips past the validator, it can only see the current tenant's rows. The LLM is told explicitly not to add a tenant filter; the validator would strip it anyway if it tried to be "helpful" and add a wrong one.

### RAG + citation
Three KB files (rates.md, reviews.md, onboarding.md) scored by term overlap. Simple and fast — no embedding API needed for 3 files. The prompt instructs Claude to include `[Source: filename.md]` in the answer; we extract it with regex and return it as `source` in the response. For a larger KB (50+ articles), would switch to pgvector embeddings.

### Console realtime + states
Poll every 8 seconds on `/events` and `/bookings`. Three explicit UI states per component: loading (skeleton), empty (empty state message), error (red banner with retry). No business logic in the frontend — all filtering/scoping/decisions happen in the backend. Mobile-first: max-width 900px, flex wrapping, 14px base font.
