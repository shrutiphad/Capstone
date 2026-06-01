# AI_LOG.md — AI Tool Usage

## Tools Used
- Claude (Anthropic) — architecture design, code generation, test strategy
- GitHub Copilot — inline autocomplete during editing

---

## Where AI Helped

### Architecture
Asked Claude to help structure the 2-stage classifier (rules → LLM) so Stage 1 doesn't call the API for obvious cases. This was a genuine improvement — naive LLM-only classify was ~800ms; hybrid is <5ms for high-confidence messages.

### SQL Guard
Asked Claude to generate the SQL validation function. The initial version only checked for INSERT/UPDATE/DELETE at the start of the query. **I caught a gap**: it didn't block injection via UNION SELECT or information_schema. Had to explicitly ask to add those patterns, then wrote unit tests to confirm.

### Tenant Injection
Claude initially suggested trusting the LLM to include `WHERE property_id = $1` in generated SQL. **I rejected this** — the spec explicitly says "never trust the LLM" for tenant scope. I redesigned the approach to wrap every LLM-generated query in a Python subquery filter before execution.

### RAG
Claude suggested using embeddings + cosine similarity for KB search. Given the KB has only 3 files and the assignment is time-boxed, I used simpler term-overlap scoring instead. The trade-off is documented — for 100+ KB articles, vector search would be necessary.

### Tests
Claude generated test skeletons. I extended them with the adversarial cases (injection patterns, ambiguous cancellation phrases, cross-tenant probes) because the initial test suite was too happy-path-heavy.

---

## Where AI Was Wrong

1. **Async pool initialisation** — Claude suggested using `psycopg2` with sync calls. This would have blocked the event loop. Caught it during review, switched to `asyncpg` throughout.

2. **RLS policy creation** — Claude generated `CREATE POLICY` without `IF NOT EXISTS`, causing startup failures on re-deployment. Fixed with the `DO $$ BEGIN ... IF NOT EXISTS ... END $$` pattern.

3. **Cancellation guard** — First draft auto-cancelled on any message classified as "cancellation" above the general confidence threshold. This violates the spec's "false-positive guard" requirement. I added `CANCEL_CONFIDENCE_THRESHOLD` as a separate, higher bar.

4. **Pydantic v2** — Claude initially generated `from pydantic import BaseSettings` which only works in Pydantic v1. It's in `pydantic-settings` in v2. Caught it when requirements install failed.

---

## Design Decisions

- **asyncpg over SQLAlchemy** — lighter, native async, works perfectly with asyncpg's transaction API for RLS `set_config` calls.
- **In-process queue** — for this assignment, `asyncio.Queue` is sufficient and avoids Redis/Celery complexity. For production with 100 hotels, would move to a proper message broker.
- **Two confidence thresholds** — `CONFIDENCE_THRESHOLD=0.6` for general handoff, `CANCEL_CONFIDENCE_THRESHOLD=0.75` specifically for cancellation. This is the key guard against the hard-fail scenario.
- **Subquery tenant injection** — safer than appending `AND property_id = $1` to the WHERE clause, because the LLM-generated query might not have a WHERE clause at all.
