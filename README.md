# Hotel Receptionist — Engineering Capstone

Multi-tenant AI receptionist + data assistant + owner console.

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Guest Message  →  POST /message                │
│    ↓ 2-stage classify (rules → LLM)             │
│    ↓ asyncio.Queue (non-blocking)               │
│    ↓ WorkflowRegistry handler                   │
│    ↓ Postgres (RLS, tenant-scoped)              │
├─────────────────────────────────────────────────┤
│  Owner /ask  →  is_product_question?            │
│    ├── YES → RAG over kb/ + citation            │
│    └── NO  → NL→SQL guard → read-only exec      │
├─────────────────────────────────────────────────┤
│  Owner Console (React/TS) → /events /bookings   │
│    polls every 8s, mobile-first dark UI         │
└─────────────────────────────────────────────────┘
```

## Quick Start (Docker — recommended)

```bash
git clone <your-repo>
cd hotel-receptionist

# 1. Copy and fill .env
cp .env.example .env
# → Set ANTHROPIC_API_KEY

# 2. Start everything
docker compose up --build

# Backend:  http://localhost:8000
# Console:  http://localhost:3000
# Mock OTA: http://localhost:9000
```

## Quick Start (Local)

### Prerequisites
- Python 3.12+
- Node.js 20+
- PostgreSQL 15+ running locally

```bash
# 1. Backend
cd backend
pip install -r requirements.txt
cp ../.env.example ../.env
# Edit .env — set ANTHROPIC_API_KEY and DATABASE_URL

uvicorn app.main:app --reload --port 8000

# 2. Mock OTA (separate terminal)
python backend/mock_ota/mock_ota_server.py

# 3. Frontend (separate terminal)
cd frontend
npm install
VITE_API_URL=http://localhost:8000 npm run dev
# Open http://localhost:3000
```

## Running Tests

```bash
# Install test deps
pip install -r tests/requirements.txt

# Unit tests only (no backend needed)
pytest tests/test_units.py -v

# Full suite (backend must be running)
BASE_URL=http://localhost:8000 pytest tests/ -v

# Run specific file
BASE_URL=http://localhost:8000 pytest tests/test_orchestration.py -v
```

## Deployment (Render)

### Backend (Web Service)
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Root Directory: `backend`
- Environment Variables:
  - `ANTHROPIC_API_KEY` → your key
  - `DATABASE_URL` → Postgres connection string (Render provides this)
  - `OTA_URL` → URL of deployed mock_ota service

### Mock OTA (Web Service)
- Build Command: `pip install -r requirements.txt` (none needed, stdlib only)
- Start Command: `python mock_ota_server.py`
- Root Directory: `backend/mock_ota`

### Frontend (Static Site)
- Build Command: `npm install && npm run build`
- Publish Directory: `dist`
- Root Directory: `frontend`
- Environment Variable: `VITE_API_URL` → deployed backend URL

### Database
- Use Render PostgreSQL (free tier)
- Schema + RLS applied automatically on first startup

## API Reference

### Part A — Orchestration

| Method | Path | Description |
|---|---|---|
| POST | `/property` | Register/update a tenant property |
| POST | `/message` | Classify + route guest message (idempotent on `message_id`) |
| GET | `/events?property_id=X` | Tenant-scoped event feed |
| GET | `/bookings?property_id=X` | Tenant-scoped bookings |
| GET | `/messages?property_id=X` | Tenant-scoped message logs |

### Part B — Data Assistant

| Method | Path | Description |
|---|---|---|
| POST | `/ask` | `{property_id, question}` → `{answer, sql, rows, source, type}` |

### Health

| Method | Path | Description |
|---|---|---|
| GET | `/health` | `{ok: true}` |
| GET | `/metrics` | `{classify_p95_ms}` |

## Guards Summary

| Guard | Mechanism |
|---|---|
| Tenant isolation | Postgres RLS (`app.current_property_id` via `set_config`) |
| Cancellation false-positive | Separate `CANCEL_CONFIDENCE_THRESHOLD=0.75` (higher than general 0.6) |
| Low-confidence → handoff | `confidence < CONFIDENCE_THRESHOLD` → `status=needs_human` |
| Idempotency | `message_id UNIQUE` in `message_logs`, checked before any action |
| SQL injection | Python regex validator before execution |
| Write query block | Regex + must-be-SELECT check |
| Cross-tenant SQL | Python subquery wrapper + RLS (2 layers) |
| LLM hallucination | Schema grounding prompt + UNANSWERABLE path |

## Project Structure

```
.
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI routes
│   │   ├── classify.py      # 2-stage intent classifier
│   │   ├── queue_worker.py  # Async queue + workflow handlers
│   │   ├── nl_sql.py        # NL→SQL guard + execution
│   │   ├── rag.py           # RAG over kb/
│   │   ├── database.py      # asyncpg pool + RLS helpers
│   │   ├── models.py        # Pydantic request/response models
│   │   ├── config.py        # Settings (env)
│   │   └── seed.py          # DB seeder
│   ├── kb/                  # Knowledge base articles (Markdown)
│   ├── seed/                # Schema SQL + seed data + properties.json
│   ├── mock_ota/            # Mock OTA channel manager (:9000)
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.tsx          # Main console with tabs + property switcher
│   │   ├── api.ts           # All backend calls
│   │   └── components/
│   │       ├── EventsFeed.tsx     # Live events (auto-poll)
│   │       ├── BookingsList.tsx   # Bookings table
│   │       └── AskAssistant.tsx   # NL ask box + SQL display
│   ├── package.json
│   └── Dockerfile
├── tests/
│   ├── conftest.py          # Fixtures, BASE_URL, property IDs
│   ├── test_units.py        # Unit tests (no network)
│   ├── test_orchestration.py# Part A integration tests
│   ├── test_data_assistant.py# Part B integration tests
│   └── test_console.py      # Part C smoke tests
├── docker-compose.yml
├── pytest.ini
├── TESTING.md
├── RESULTS.md
└── AI_LOG.md
```
