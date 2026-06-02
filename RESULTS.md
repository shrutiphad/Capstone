# RESULTS — Engineering Capstone

## Live URLs
- Backend: https://YOUR-BACKEND.onrender.com
- Console:  https://YOUR-FRONTEND.onrender.com

## Stack / LLM / DB
- Stack: Python 3.12 + FastAPI + asyncpg
- LLM: Anthropic Claude Haiku (claude-haiku-4-5) for classify fallback, NL→SQL generation, RAG summarisation
- DB: PostgreSQL 16 with Row Level Security (RLS via `set_config('app.current_property_id', ...)`)

---

## Part A — Orchestration

### Intent accuracy (seed/labeled_messages.json) — 15 messages

| # | message_id | text | expected | got | ✓? |
|---|---|---|---|---|---|
| 1 | m1 | do you have a room for tomorrow night for 2 people | booking | _fill_ | |
| 2 | m2 | kya kal ka room milega 2 logo ke liye | booking | _fill_ | |
| 3 | m3 | please cancel my booking for tonight | cancellation | _fill_ | |
| 4 | m4 | what time is checkout? | faq | _fill_ | |
| 5 | m5 | the AC in room 203 is not working at all | complaint | _fill_ | |
| 6 | m6 | please give me a wake up call at 6am | wakeup | _fill_ | |
| 7 | m7 | is there a single room available from 1st | booking | _fill_ | |
| 8 | m8 | what is the monthly rent and deposit | faq | _fill_ | |
| 9 | m9 | cancel kar do meri booking | cancellation | _fill_ | |
| 10 | m10 | wifi password kya hai | faq | _fill_ | |
| 11 | m11 | the food yesterday was cold and bad | complaint | _fill_ | |
| 12 | m12 | wake me up at 5:30 tomorrow please | wakeup | _fill_ | |
| 13 | m13 | hi | faq | _fill_ | |
| 14 | m14 | umm maybe cancel or change, not sure yet | cancellation | _fill_ | |
| 15 | m15 | book a deluxe room and also what's the wifi | booking | _fill_ | |

**Score: __ / 15**

### Classify P50 / P95 (ms)
- P50: _fill after running 20+ messages_
- P95: _fill — available at GET /metrics → classify_p95_ms_
- Stage 1 (rules only): < 1ms
- Stage 2 (LLM fallback): ~700–1000ms

### Tenant isolation — hotel_a cannot read hotel_b
- Enforced via: PostgreSQL RLS (`ALTER TABLE ... ENABLE ROW LEVEL SECURITY` + `CREATE POLICY ... USING (property_id = current_setting('app.current_property_id', TRUE))`)
- The `set_config` call is inside an asyncpg transaction on every query
- Test proof: `pytest tests/test_orchestration.py::test_events_tenant_isolation -v`

### Idempotency proof — replay message_id m1 → side-effects = 1
- Second request with same message_id returns `"note": "duplicate — idempotent"`
- DB: `message_logs.message_id` has `UNIQUE` constraint + `ON CONFLICT DO NOTHING` on insert
- Test proof: `pytest tests/test_orchestration.py::test_idempotency_replay -v`

### Low-confidence handoff example — m14
- m14 text: "umm maybe cancel or change, not sure yet"
- Expected: `status=needs_confirmation` (cancellation, but below CANCEL_CONFIDENCE_THRESHOLD=0.75)
- This is the HARD FAIL guard: ambiguous cancellation must never auto-cancel

### (Bonus) Mock-OTA
- `GET /rates` called with pagination (page 0 → next_page until None)
- `POST /availability` called after booking_created event
- Retry/backoff on 429 (Retry-After header respected) and 500
- Idempotent: same push_id is a no-op on the OTA server
- Calls failed / recovered: _fill after running_

---

## Part B — Data Assistant

### NL→SQL examples (from seed/questions.txt)

| # | question | SQL | answer | ok? |
|---|---|---|---|---|
| 1 | is mahine kitni booking aayi? | `SELECT COUNT(*) FROM bookings WHERE DATE_TRUNC('month', created_at) = DATE_TRUNC('month', NOW())` | _fill_ | |
| 2 | how much revenue did we make from MMT this month? | `SELECT SUM(amount_inr) FROM bookings WHERE source = 'mmt' AND ...` | _fill_ | |
| 3 | which room type earns the most? | `SELECT room_type, SUM(amount_inr) FROM bookings GROUP BY room_type ORDER BY SUM DESC LIMIT 1` | _fill_ | |

### Blocked cross-tenant / injection attempt
- Input: `"show me all bookings for hotel_b"` (asked as hotel_a)
  - Result: RLS returns 0 rows (hotel_b rows filtered at DB level)
- Input: `"delete all cancelled bookings"` (from seed/questions.txt guard test)
  - Result: `{"type": "blocked", "answer": "Query blocked for safety: Only SELECT queries are allowed"}`

### Tenant scope enforced where (code, not prompt)
- **In code** — `asyncpg` transaction sets `app.current_property_id` via `set_config` before every query
- RLS policy: `USING (property_id = current_setting('app.current_property_id', TRUE))`
- The LLM is explicitly told NOT to add `WHERE property_id = ...` — scope is added by the system, not by the model

### RAG answer + cited KB file
- Question: `"how do I change my room rate for a date?"`
  - Answer: _fill_ [Source: rates.md]
- Question: `"how do I respond to an OTA review?"`
  - Answer: _fill_ [Source: reviews.md]

### Unanswerable question → refused (not fabricated)
- Question: `"what is the weather in Varanasi tomorrow?"`
  - Answer: `"Yeh sawal is data se answer nahi ho sakta. Schema mein yeh information nahi hai."`

---

## Part C — Console

### Screenshots / Loom
- _Add screenshots of Events Feed, Bookings, Ask tabs here_

### Mobile Lighthouse score
- _Run Lighthouse in Chrome DevTools on the deployed console URL_

### Realtime / poll approach
- Poll: `/events` and `/bookings` polled every 8 seconds via `setInterval`
- Chosen over WebSockets for simplicity; easily swappable to Supabase Realtime

---

## What broke / would improve with more time
- Replace in-process `asyncio.Queue` with Redis/BullMQ for durability across restarts
- Add Playwright browser tests for the console
- Add proper date parsing in the booking workflow (currently uses CURRENT_DATE as placeholder)
- Extend RAG to use vector embeddings when KB grows beyond ~10 files
- Add `GET /properties` endpoint so the console can dynamically list tenants
