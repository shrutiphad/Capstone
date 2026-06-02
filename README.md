# Engineering Capstone — Multi-Tenant Receptionist + Data Assistant + Owner Console

## One-command test run
```bash
BASE_URL=http://localhost:8000 pytest tests/ -v
```

## Architecture

```
POST /message  →  2-stage classify (rules < 1ms → LLM fallback)
               →  asyncio.Queue  (non-blocking, returns immediately)
               →  WorkflowRegistry handler
               →  Postgres (RLS via set_config, tenant-scoped)

POST /ask  →  is_product_question?
              ├── YES → RAG over kb/ (rates.md, reviews.md, onboarding.md) + citation
              └── NO  → NL→SQL: Python guard → read-only RLS transaction

GET /events, GET /bookings  →  tenant-scoped (RLS enforced)

Frontend: React/TS SPA, property switcher (hotel_a / hotel_b), 3 tabs,
          polls /events + /bookings every 8s
```

## Quick start — Docker (recommended)

```bash
git clone <your-repo-url>
cd hotel-receptionist

cp .env.example .env
# → Edit .env: set ANTHROPIC_API_KEY

docker compose up --build

# Backend:  http://localhost:8000
# Console:  http://localhost:3000
# Mock OTA: http://localhost:9000/rates, /availability
```

## Quick start — Local

### Prerequisites: Python 3.12+, Node 20+, PostgreSQL 16 running

```bash
# 1. Copy env
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY and DATABASE_URL

# 2. Backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 3. Mock OTA (new terminal)
python backend/mock_ota/mock_ota_server.py

# 4. Frontend (new terminal)
cd frontend
npm install
VITE_API_URL=http://localhost:8000 npm run dev
# → http://localhost:3000
```

## Running tests

```bash
pip install -r tests/requirements.txt

# Unit tests (no backend needed)
pytest tests/test_units.py -v

# Full suite (backend must be running)
BASE_URL=http://localhost:8000 pytest tests/ -v

# Single file
BASE_URL=http://localhost:8000 pytest tests/test_orchestration.py -v
```

## Deploying to Render

### 1. PostgreSQL
Create a Render PostgreSQL instance. Copy the external connection string.

### 2. Mock OTA (Web Service)
- Root Directory: `backend/mock_ota`
- Build Command: _(none)_
- Start Command: `python mock_ota_server.py`
- Port: 9000

### 3. Backend (Web Service)
- Root Directory: `backend`
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Env vars:
  - `ANTHROPIC_API_KEY` → your key
  - `DATABASE_URL` → Render Postgres connection string
  - `OTA_URL` → https://your-mock-ota.onrender.com

### 4. Frontend (Static Site)
- Root Directory: `frontend`
- Build Command: `npm install && npm run build`
- Publish Directory: `dist`
- Env var: `VITE_API_URL` → https://your-backend.onrender.com

Schema + RLS + seed data are applied automatically on first backend startup.

## API Reference

### Part A — Orchestration
```
POST /property          {property_id, name, language?, custom_faqs?}
POST /message           {property_id, guest_id, message_id, text}
GET  /events            ?property_id=hotel_a&limit=50
GET  /bookings          ?property_id=hotel_a&limit=50
GET  /messages          ?property_id=hotel_a&limit=50
```

### Part B — Data Assistant
```
POST /ask               {property_id, question}
                        → {answer, sql, rows, source, type}
                           type: data | rag | blocked | refused | error
```

### Health / Metrics
```
GET  /health            → {ok: true}
GET  /metrics           → {classify_p95_ms: float}
```

## Guard summary

| Guard | Mechanism |
|---|---|
| Tenant isolation | PostgreSQL RLS — `set_config('app.current_property_id', ...)` in every transaction |
| Ambiguous cancel | `CANCEL_CONFIDENCE_THRESHOLD=0.75` separate from general `CONFIDENCE_THRESHOLD=0.6` |
| Low-confidence handoff | `confidence < 0.6` → `status=needs_human`, no workflow fired |
| Idempotency | `message_logs.message_id UNIQUE` + check-before-act |
| SQL injection | Python regex guard: blocks all non-SELECT, UNION, information_schema, pg_*, multi-statement |
| Cross-tenant NL→SQL | RLS enforced in the same read-only transaction as the LLM-generated query |
| Write query block | Must match `^\s*SELECT\b` — anything else raises `SQLGuardError` |

## Seed data

- `hotel_a` — Hotel Surya (Varanasi): 3 room types, 5 bookings (bk1–bk5)
- `hotel_b` — Coastal Stay PG (Bengaluru): 2 room types, 2 bookings (bk6–bk7)
- KB: `rates.md`, `reviews.md`, `onboarding.md`

## Project structure

```
├── backend/
│   ├── app/
│   │   ├── main.py          FastAPI routes (Parts A + B)
│   │   ├── classify.py      2-stage intent classifier
│   │   ├── queue_worker.py  asyncio.Queue + workflow handlers + OTA push
│   │   ├── nl_sql.py        NL→SQL guard + execution
│   │   ├── rag.py           RAG over kb/ with citation
│   │   ├── database.py      asyncpg pool + RLS helpers + schema migration
│   │   ├── models.py        Pydantic request/response models
│   │   ├── config.py        Settings from .env
│   │   └── seed.py          properties.json + data.sql seeder
│   ├── kb/                  rates.md, reviews.md, onboarding.md
│   ├── seed/                schema.sql, data.sql, properties.json,
│   │                        labeled_messages.json, questions.txt
│   ├── mock_ota/            mock_ota_server.py (exact from starter)
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.tsx          Console: tabs + property switcher (hotel_a/hotel_b)
│   │   ├── api.ts           All backend calls
│   │   └── components/
│   │       ├── EventsFeed.tsx     Live events (poll 8s)
│   │       ├── BookingsList.tsx   Bookings table
│   │       └── AskAssistant.tsx   Ask box + SQL + rows
│   └── Dockerfile
├── tests/
│   ├── conftest.py          Fixtures, BASE_URL, hotel_a/hotel_b
│   ├── test_units.py        Unit tests (no network — classifier, guard, heuristic)
│   ├── test_orchestration.py  Part A: 15 seed messages, guards, idempotency, isolation
│   ├── test_data_assistant.py Part B: NL→SQL guards, injection, RAG, cross-tenant
│   └── test_console.py      Part C: API shapes, seed booking IDs, error states
├── docker-compose.yml
├── pytest.ini
├── .env.example
├── README.md
├── TESTING.md
├── RESULTS.md
└── AI_LOG.md
```
