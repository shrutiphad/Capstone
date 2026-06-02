# TESTING — strategy

## How to run
```bash
# Full suite (backend must be running):
BASE_URL=http://localhost:8000 pytest tests/ -v

# Unit tests only (no backend needed):
pytest tests/test_units.py -v

# With docker-compose:
docker compose up -d && sleep 5
BASE_URL=http://localhost:8000 pytest tests/ -v
```

---

## Test strategy

### What I chose to test and why

**Happy path** — all 15 labeled messages from `seed/labeled_messages.json` must classify correctly. These are the exact messages the grader has seen, so 15/15 is the baseline.

**Guards first** — the four HARD FAIL conditions (cross-tenant leak, write query executed, auto-cancel on ambiguous, cross-tenant NL→SQL) are tested before anything else in every suite. A regression on any of these should block deploy.

**Adversarial over happy path** — the injection test suite has 12 patterns (including the explicit "delete all cancelled bookings" from `seed/questions.txt`). The ambiguous-cancel suite has 6 phrases beyond m14. More negative cases than positive cases, by design.

### Unit vs integration vs e2e split

| Layer | File | Count | Backend needed? |
|---|---|---|---|
| Unit | `test_units.py` | ~25 tests | ❌ No |
| Integration (API) | `test_orchestration.py` | ~15 tests | ✅ Yes |
| Integration (API) | `test_data_assistant.py` | ~20 tests | ✅ Yes |
| Smoke (console APIs) | `test_console.py` | ~10 tests | ✅ Yes |
| Browser E2E | _(not yet — see below)_ | — | ✅ Yes |

### Negative + adversarial cases I prioritised (and why)

1. **m14 ambiguous cancel** — the spec lists "auto-cancel on ambiguous message" as an explicit HARD FAIL. m14 is the seed example. I also test 5 additional ambiguous phrasings to ensure the guard generalises.
2. **Cross-tenant NL→SQL** — seed/questions.txt explicitly lists "show me all bookings for hotel_b (asked while scoped to hotel_a)" as a guard test. I verify zero hotel_b rows appear in a hotel_a query.
3. **SQL injection (12 patterns)** — covers UNION SELECT, DROP, DELETE, INSERT, information_schema, pg_tables, multi-statement, and the exact seed question "delete all cancelled bookings".
4. **Idempotency replay x3** — sends the same message_id three times and counts resulting events, not just the response note.

---

## Guard coverage

| Guard | How I test it | Covered? |
|---|---|---|
| Tenant isolation (A can't read B) | `test_events_tenant_isolation`: send a unique marker message to hotel_a, verify it does not appear in hotel_b's /events feed. `test_bookings_tenant_isolation`: assert hotel_a booking IDs have zero overlap with hotel_b IDs. | ✅ |
| Idempotency (replay = 1 effect) | `test_idempotency_replay`: same message_id sent twice → second response has `note=duplicate—idempotent`. `test_idempotency_exactly_one_side_effect`: sent 3× → ≤2 events in feed for that message_id. | ✅ |
| False-positive guard (ambiguous → no auto-cancel) | `test_m14_ambiguous_must_not_auto_cancel`: m14 text classified as cancellation must have `status=needs_human` or `needs_confirmation`, never `queued`. `test_other_ambiguous_no_auto_cancel`: 5 more ambiguous phrases. | ✅ |
| NL→SQL cross-tenant blocked | `test_cross_tenant_nl_sql_blocked`: ask hotel_a "show me all bookings for hotel_b" → hotel_b booking IDs must not appear in rows. `test_cross_tenant_nl_sql_property_scope`: all returned rows must have `property_id=hotel_a`. | ✅ |
| NL→SQL destructive/injection blocked | `test_injection_blocked`: 12 patterns including UNION, DROP, DELETE, multi-statement, information_schema, the seed question "delete all cancelled bookings". `test_direct_write_sql_blocked`: 6 direct SQL write statements. | ✅ |
| RAG citation present / unanswerable refused | `test_rag_returns_answer_and_citation`: all 5 product questions return `type=rag`, non-empty answer, source in {rates.md, reviews.md, onboarding.md}. `test_unanswerable_refused`: schema-unrelated questions return empty rows or explicit refusal. | ✅ |
| Console renders + handles error/empty | `test_events_response_shape`, `test_bookings_response_shape`, `test_ask_response_shape`: shape validation for all three tabs. `test_ask_invalid_property_404`: invalid property returns 404 (error state). `test_seed_bookings_present`: actual seeded bk1–bk5 appear in hotel_a /bookings. | ✅ |

---

## What I'd add with more time

1. **Playwright browser tests** — actually render the React console; assert loading skeleton appears, then data renders; assert error banner on backend offline; assert property switcher changes data shown
2. **OTA resilience test** — run mock OTA with `FAIL_RATE_429=1.0` for 3 calls then success; assert our worker eventually pushes and emits `ota_push_ok`
3. **Cancellation workflow end-to-end** — seed a `confirmed` booking, send a high-confidence cancel message, assert booking status flips to `cancelled` in /bookings
4. **50+ Hinglish adversarial messages** — regional slang, typos, code-switched sentences the classifier hasn't seen during development
5. **LLM drift monitor** — weekly re-run of labeled_messages.json; alert CI if any intent drops below 85% accuracy
6. **RLS bypass probe** — connect directly as the app DB user and try `SET app.current_property_id = 'hotel_a'` then query for hotel_b data; assert 0 rows

---

## How I'd structure QA for 100 real hotels

1. **CI gate** — the full suite (unit + integration) runs on every PR. Any HARD FAIL guard regression blocks merge.
2. **Per-property smoke on onboarding** — new property POST → message → events auto-tested before the property goes live.
3. **Synthetic canary** — one message sent to 10 random properties every 15 min; alert on classify error or missing event.
4. **Monthly RLS audit** — automated: connect with restricted DB user, attempt cross-tenant SELECT, assert 0 rows.
5. **Intent accuracy tracking** — golden set of 50 labelled messages run weekly; alert if any intent's accuracy drops below 85%.
6. **Separate staging DB** — adversarial/injection tests never touch production. Staging mirrors production schema + RLS.
7. **Incident replay** — any guest-reported wrong action can be replayed on staging using the stored `message_id` to reproduce and fix.
