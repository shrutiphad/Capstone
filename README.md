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

## Part D — QA & Testing (this matters — we read it closely)
We want to see how you *think about correctness*, not just that the happy path runs.
- Write a **runnable e2e test suite** (`pytest`, `vitest`/`jest`+supertest, Playwright — your call) that exercises the critical paths **and the guards**, against your API (local or deployed):
  - intent classification on a few messages (incl. an ambiguous one that must **not** auto-cancel),
  - **tenant isolation** — property A cannot read/write B (assert it),
  - **idempotency** — replaying a `message_id` produces exactly one side-effect,
  - **NL→SQL safety** — a cross-tenant question and a destructive/injection attempt are **blocked**,
  - RAG returns a citation; an unanswerable question is refused (not fabricated),
  - a console smoke test (loads, calls backend, renders a state).
- Write **`TESTING.md`** — your test strategy: what you chose to test and **why**, the unit/integration/e2e split, the negative + adversarial cases you prioritised, what you'd add with more time, and how you'd structure QA for a multi-tenant platform going to 100 real hotels.
- Include **negative and adversarial cases**, not just happy path. `README` must say how to run the tests in one command.

---

## ⚠️ How we grade — we will run YOUR live endpoint with inputs you have NOT seen
The seed data is for you to build against. At grading we hit your **deployed API** with a **held-out set** of our own messages and questions — including trickier Hinglish, mixed-intent, ambiguous, cross-tenant, and injection cases. Hard-coding to the seed will fail. Build for the general case; your own tests should reflect that.

---

## Deliver
1. Public GitHub repo (real commit history — incremental, not one dump).
2. **Live URLs** — deployed backend + deployed console (both reachable).
3. `RESULTS.md` — intent accuracy (15 seed msgs) · classify P95 · tenant-isolation proof · idempotency proof · a low-confidence handoff · 3 NL→SQL examples (question→SQL→answer) · one **blocked** cross-tenant/injection attempt · one RAG answer with citation · (bonus) OTA calls failed-and-recovered count · console screenshots/Loom.
4. **`TESTING.md` + a runnable e2e test suite** (one-command run) — see Part D.
5. `AI_LOG.md` — tools, prompts, where AI was wrong + how you caught it, key design decisions.

## AI traps (each silently fails on real data)
- Side-effects inline instead of on a queue.
- Tenancy via app-code `WHERE` instead of RLS.
- No idempotency → double-fires on replay.
- Auto-cancel on an ambiguous message.
- Executing LLM SQL without forcing tenant scope / read-only → cross-tenant or destructive.
- Hallucinated columns returned as fact.
- Desktop-only console with no loading/error states.

## Rules
- **AI tools allowed + encouraged** — judgment is what we score; log it honestly.
- **Stack:** TypeScript preferred (Deno/Node) for backend; React+TS for console. Python/FastAPI backend accepted. Supabase covers Postgres+RLS+realtime if you want it.
- **Timebox: 3 days** (it's broad on purpose). Reply in the group when you start.
- **Follow-up:** 45-min live — modify code on the spot + explain a guard.

Scope tip: a correct, deployed A + B with a thin working C beats a pretty C with leaky guards. Build the guards first.
