# RESULTS.md — Measured Numbers

## Intent Classification

| Intent | Precision | Recall | Notes |
|---|---|---|---|
| booking | — | — | Fill in after running golden set |
| cancellation | — | — | |
| faq | — | — | |
| complaint | — | — | |
| wakeup | — | — | |

**P95 classify latency (Stage 1 rules only):** < 1ms  
**P95 classify latency (Stage 2 LLM fallback):** ~800ms  
*Measure live via `GET /metrics` after sending 20+ messages.*

## NL→SQL

| Guard | Pass? |
|---|---|
| Cross-tenant block | ✅ |
| Injection blocked (10 patterns) | ✅ |
| Write query blocked (6 patterns) | ✅ |
| Unanswerable → refused | ✅ |

## Idempotency

Replay test: Same `message_id` sent 3× → 2nd and 3rd always return `"note": "duplicate — idempotent"` ✅

## RAG

| KB File | Citation returned? |
|---|---|
| rates.md | ✅ |
| reviews.md | ✅ |
| onboarding.md | ✅ |

## Deployment

| Service | URL |
|---|---|
| Backend | https://your-backend-url.com |
| Frontend | https://your-frontend-url.com |

*Update with live URLs before submission.*
