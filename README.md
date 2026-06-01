# Engineering Capstone — Multi-Tenant Receptionist + Data Assistant + Owner Console

A single full-stack build that mirrors the real platform end to end. Three parts share **one multi-tenant Postgres** and **one deployment**. Pitched a notch above day-to-day work — we want to see range + judgment, not just one slice.

**Final-round task. Prioritise correctness of the guards (tenant isolation, idempotency, SQL safety) over UI polish.**

---

## Part A — Conversation Orchestration + Lifecycle (backend)
A service exposing:
- `POST /property` — register a tenant + `property_config` (custom FAQs, language). Seed both from `seed/properties.json`.
- `POST /message` `{property_id, guest_id, message_id, text}`:
  1. **2-stage intent classify** (fast rules → LLM fallback): `booking · cancellation · faq · complaint · wakeup`.
  2. Route via a **WorkflowRegistry** (one workflow per intent).
  3. Fire side-effects **through a queue/event** (not inline) — e.g. `booking` → create a booking row + enqueue a confirmation event.
- `GET /events?property_id=` and `GET /bookings?property_id=` — tenant-scoped.

**Must:** tenant isolation via **RLS** (not app-code) · **idempotent** on `message_id` · **false-positive guard** (no auto-cancel on low confidence — confirm) · **human-handoff** below a confidence threshold · report classify **P95**.

**Bonus (resilience):** the `booking` workflow pushes availability to the **mock OTA** (`python mock_ota/mock_ota_server.py` → `:9000`, paginated, random 429/500, idempotent on `push_id`). Survive failures with retry/backoff; make the push idempotent.

## Part B — Data Assistant: Hinglish NL→SQL + RAG (backend)
- `POST /ask` `{property_id, question}`:
  - Data question → **NL→SQL** in a **read-only, tenant-scoped sandbox** → `{answer, sql, rows}`.
  - Product-help question → **RAG** over `kb/` with a **citation**.
- HMS data is seeded by `seed/schema.sql` + `seed/data.sql` (2 tenants). Sample qs in `seed/questions.txt`.

**Must:** tenant scope **enforced in your code** (never trust the LLM to add it) · block any non-SELECT / multi-statement / cross-tenant read · **schema-grounded** (no hallucinated columns; unanswerable → refuse, don't fabricate) · RAG answers cite the KB file.

## Part C — Owner Console (frontend)
A React + TS SPA (mobile-first, Hinglish-friendly) that talks to A and B:
- A **lifecycle feed** — recent messages/bookings/events for the logged property (from `/events`, `/bookings`), updating live-ish (realtime or poll).
- An **Ask the Assistant** box — type a question, show the answer + (for data) the SQL it ran.
- Graceful **loading / empty / error** states.

**Must:** mobile-first, no business logic in the frontend, sane states. Polish is secondary to it working end-to-end against your deployed backend.
