# TESTING.md — QA Strategy

## One-Command Run

```bash
# With backend already running locally:
BASE_URL=http://localhost:8000 pytest tests/ -v

# Or with docker-compose:
docker compose up -d
BASE_URL=http://localhost:8000 pytest tests/ -v

# Unit tests only (no backend needed):
cd backend && pip install -r requirements.txt && \
  BASE_URL=http://localhost:8000 pytest ../tests/test_units.py -v
```

---

## Test Architecture

### Unit Tests (`test_units.py`)
No network, no DB. Pure Python function tests.
- `_rule_classify()` — Stage-1 keyword classifier for all 5 intents, English + Hinglish
- `_validate_sql()` — SQL guard: rejects INSERT/UPDATE/DELETE/DROP/TRUNCATE, multi-statement, injection, unknown tables, `information_schema`, `pg_*`
- `is_product_question()` — RAG vs SQL routing heuristic

### Integration / E2E Tests (need running backend)
- `test_orchestration.py` — Part A: intent classification, guards, idempotency, tenant isolation
- `test_data_assistant.py` — Part B: NL→SQL guards, cross-tenant block, injection, RAG citation/refusal
- `test_console.py` — Part C: API shapes and console smoke tests

---

## What We Test and Why

### Critical Path (Happy Path)
- All 5 intent classes in both English and Hinglish
- Booking, FAQ, complaint, wakeup workflows queue correctly
- NL→SQL returns `{answer, sql, rows}` for valid data questions
- RAG returns `{answer, source}` with file citation for product questions
- `/events` and `/bookings` return correct paginated shapes

### Guards (the hard bits we test most carefully)

#### 1. Ambiguous Cancellation (HARD FAIL)
`test_ambiguous_must_not_auto_cancel` — parameterized over 4 ambiguous phrases.  
Any message that could mean "cancel" but isn't explicit must go to `needs_human`/`needs_confirmation`, never to `queued` with cancellation workflow.  
Why: Auto-cancelling a real booking on an ambiguous message is an unrecoverable business error.

#### 2. Tenant Isolation (HARD FAIL)
`test_events_tenant_isolation`, `test_bookings_tenant_isolation`, `test_nl_sql_tenant_isolation`.  
A query under PROP_B must never return PROP_A data. Tested at the API level and inside NL→SQL output rows.  
Why: Data leakage between hotel properties is a critical privacy/compliance failure.

#### 3. SQL Injection (HARD FAIL)
10 injection patterns including: UNION SELECT, `information_schema`, `pg_tables`, multi-statement, DROP, DELETE.  
Why: The LLM could be prompted into generating malicious SQL. The Python guard must catch it regardless.

#### 4. Write Query Blocking (HARD FAIL)
Direct SQL write commands sent as "questions". Must always return `blocked`.  
Why: The `/ask` endpoint is read-only. Any write succeeding would be a catastrophic bug.

#### 5. Idempotency
Same `message_id` sent twice → second response carries `"note": "duplicate — idempotent"`.  
Why: Mobile clients often retry. We must not double-process bookings or events.

#### 6. Schema Grounding / Refusal
Questions that can't be answered from schema → refused, not fabricated.  
Why: A confident wrong answer (e.g., hallucinated revenue figures) is worse than "I don't know".

---

## Negative & Adversarial Cases

| Case | Test | Why |
|---|---|---|
| Ambiguous "cancel" → no auto-cancel | `test_ambiguous_must_not_auto_cancel` | Hard fail |
| Cross-tenant events read | `test_events_tenant_isolation` | Hard fail |
| Cross-tenant NL→SQL | `test_nl_sql_tenant_isolation` | Hard fail |
| SQL UNION injection | `test_injection_blocked` | Hard fail |
| `information_schema` probe | `test_injection_blocked` | Hard fail |
| Multi-statement injection | `test_injection_blocked` | Hard fail |
| Direct write SQL via /ask | `test_write_query_blocked` | Hard fail |
| Message replay (idempotency) | `test_idempotency_replay` | Data integrity |
| Unknown property → 404 | `test_message_unknown_property` | Input validation |
| Completely unknown /ask question → refuse | `test_unanswerable_refused` | No hallucination |
| RAG on off-topic question | `test_rag_unknown_refused` | No hallucination |

---

## Unit / Integration / E2E Split

```
Unit (no I/O):           ~25 tests  →  fast, run on every PR
Integration (live API):  ~35 tests  →  run before deploy
E2E (full flow):         covered in integration for now
Browser (Playwright):    not yet implemented — see "What I'd Add"
```

---

## What I'd Add With More Time

1. **Playwright browser tests** — actually render the React console, check for correct data rendering, loading states, error states, tab switching, property switcher
2. **Load test with locust** — 100 concurrent `/message` requests to verify queue doesn't block
3. **OTA retry test** — mock OTA returning 429 repeatedly, verify exponential backoff + eventual success
4. **Cancellation workflow test** — seed a confirmed booking, send high-confidence cancel, verify booking status changed
5. **Hinglish adversarial set** — expand to 50+ Hinglish messages including regional slang, code-switched sentences, typos
6. **LLM drift test** — periodically re-run a fixed golden set and alert if intent accuracy drops below threshold
7. **RLS bypass attempt** — connect to Postgres directly with the app user, attempt `SET app.current_property_id = 'prop_001'` and query for PROP_002 data

---

## QA for 100 Real Hotels

At 100 hotels:
1. **CI/CD gate** — the full test suite runs on every deploy. A failing guard (cross-tenant, injection, auto-cancel) blocks the release.
2. **Property onboarding tests** — each new property gets a smoke test (`POST /property` → `POST /message` → `GET /events`) run automatically.
3. **Per-tenant canary** — a synthetic message sent to 5 random properties every 15 minutes. Alert if any fails.
4. **RLS audit** — monthly automated SQL probe: connect with a restricted role, attempt cross-tenant read, verify it returns 0 rows.
5. **Intent accuracy tracking** — a golden set of labeled messages run weekly; alert if any intent's accuracy falls below 85%.
6. **Separate staging DB** — never run adversarial/injection tests against production. Staging mirrors production schema + RLS.
7. **Incident replay** — when a guest reports a wrong action (e.g., accidental cancel), the exact message_id can be replayed on staging to reproduce and fix.
