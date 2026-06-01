# TESTING — strategy

> Tell us how you think about correctness. This doc is read closely.

## How to run
```
<one command — e.g. pytest -q  /  npm test>
```

## Test strategy
- What I chose to test and **why**:
- Unit vs integration vs e2e split:
- Negative / adversarial cases I prioritised (and why):

## Guard coverage (must address each)
| Guard | How I test it | Covered? |
|---|---|---|
| Tenant isolation (A can't read B) | | |
| Idempotency (replay = 1 effect) | | |
| False-positive guard (ambiguous → no auto-cancel) | | |
| NL→SQL cross-tenant blocked | | |
| NL→SQL destructive/injection blocked | | |
| RAG citation present / unanswerable refused | | |
| Console renders + handles error/empty | | |

## What I'd add with more time
-

## How I'd structure QA for 100 real hotels
- (regression, load, multi-tenant edge cases, monitoring, CI gating, ...)
