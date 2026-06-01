"""
Engineering Capstone — Multi-Tenant Receptionist + Data Assistant Backend
Author: (your name)

Parts:
  A — Orchestration + Lifecycle  (/property, /message, /events, /bookings)
  B — Data Assistant              (/ask)
  Health                          (/health, /metrics)
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .database import init_pool, close_pool, tenant_fetch, admin_fetch, admin_execute
from .models import Message, Ask, PropertyConfig, MessageResponse, AskResponse
from .classify import classify, get_classify_p95
from .queue_worker import enqueue, worker
from .nl_sql import execute_nl_query, SQLGuardError
from .rag import rag_answer, is_product_question
from .seed import run_seed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()

_worker_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _worker_task
    # ── startup ──────────────────────────────────────────────────────────────
    await init_pool(settings.DATABASE_URL)
    await run_seed()
    _worker_task = asyncio.create_task(worker())
    logger.info("Application started")
    yield
    # ── shutdown ─────────────────────────────────────────────────────────────
    if _worker_task:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
    await close_pool()
    logger.info("Application stopped")


app = FastAPI(title="Hotel Receptionist API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health & Metrics ──────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"ok": True, "version": "1.0.0"}


@app.get("/metrics")
async def metrics():
    return {
        "classify_p95_ms": get_classify_p95(),
    }


# ── Part A: Orchestration ─────────────────────────────────────────────────────

@app.post("/property", status_code=201)
async def create_property(config: PropertyConfig):
    """Register or update a tenant property."""
    cfg_json = json.dumps({
        "language": config.language,
        "custom_faqs": config.custom_faqs,
    })
    try:
        await admin_execute(
            """INSERT INTO properties(property_id, name, city, total_rooms, config)
               VALUES($1, $2, $3, $4, $5)
               ON CONFLICT(property_id) DO UPDATE
                 SET name=$2, city=$3, total_rooms=$4, config=$5""",
            config.property_id, config.name, config.city, config.total_rooms, cfg_json,
        )
        return {"stored": True, "property_id": config.property_id}
    except Exception as exc:
        logger.error("create_property error: %s", exc)
        raise HTTPException(500, f"DB error: {exc}")


@app.post("/message", response_model=MessageResponse)
async def handle_message(m: Message):
    """
    Idempotent on message_id.
    2-stage classify → WorkflowRegistry → ENQUEUE side-effect (not inline).
    Guards:
      - Idempotency: duplicate message_id returns cached result
      - Low confidence → human handoff (no auto-action)
      - Cancellation requires high confidence (no false-positive cancel)
    """
    # ── Idempotency check ────────────────────────────────────────────────────
    existing = await admin_fetch(
        "SELECT intent, confidence, status FROM message_logs WHERE message_id = $1",
        m.message_id,
    )
    if existing:
        row = existing[0]
        return MessageResponse(
            message_id=m.message_id,
            intent=row["intent"],
            confidence=row["confidence"],
            status=row["status"],
            note="duplicate — idempotent",
        )

    # ── Fetch property config ────────────────────────────────────────────────
    prop_rows = await admin_fetch(
        "SELECT config FROM properties WHERE property_id = $1", m.property_id
    )
    if not prop_rows:
        raise HTTPException(404, f"Property {m.property_id!r} not found")
    property_config = json.loads(prop_rows[0]["config"] or "{}")

    # ── Classify ─────────────────────────────────────────────────────────────
    intent, confidence = await classify(m.text, property_config)

    # ── Routing logic with guards ─────────────────────────────────────────────
    if confidence < settings.CONFIDENCE_THRESHOLD:
        # Too uncertain — human handoff, NO side-effects
        status = "needs_human"
        await enqueue("handoff_workflow", {
            "property_id": m.property_id, "message_id": m.message_id,
            "text": m.text, "intent": intent, "confidence": confidence,
        })
    elif intent == "cancellation" and confidence < settings.CANCEL_CONFIDENCE_THRESHOLD:
        # Cancellation false-positive guard: require higher confidence
        # Do NOT auto-cancel; escalate to human
        status = "needs_confirmation"
        await enqueue("handoff_workflow", {
            "property_id": m.property_id, "message_id": m.message_id,
            "text": m.text, "intent": intent, "confidence": confidence,
            "note": "cancellation_low_confidence",
        })
    else:
        # Route to workflow
        workflow_map = {
            "booking":      "booking_workflow",
            "cancellation": "cancellation_workflow",
            "faq":          "faq_workflow",
            "complaint":    "complaint_workflow",
            "wakeup":       "wakeup_workflow",
        }
        job_type = workflow_map.get(intent, "faq_workflow")
        await enqueue(job_type, {
            "property_id": m.property_id, "message_id": m.message_id,
            "guest_id": m.guest_id, "text": m.text,
        })
        status = "queued"

    # ── Persist message log (idempotency record) ──────────────────────────────
    try:
        await admin_execute(
            """INSERT INTO message_logs(property_id, message_id, guest_id, text, intent, confidence, status)
               VALUES($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT(message_id) DO NOTHING""",
            m.property_id, m.message_id, m.guest_id, m.text, intent, confidence, status,
        )
    except Exception as exc:
        logger.warning("message_log insert error: %s", exc)

    return MessageResponse(
        message_id=m.message_id,
        intent=intent,
        confidence=round(confidence, 3),
        status=status,
    )


@app.get("/events")
async def events(
    property_id: str = Query(..., description="Tenant property ID"),
    limit: int = Query(50, ge=1, le=200),
):
    """Tenant-scoped events feed (RLS enforced)."""
    rows = await tenant_fetch(
        property_id,
        """SELECT id, event_type, payload, created_at
           FROM events
           WHERE property_id = $1
           ORDER BY created_at DESC
           LIMIT $2""",
        property_id, limit,
    )
    return {
        "property_id": property_id,
        "events": [
            {
                "id": r["id"],
                "event_type": r["event_type"],
                "payload": json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ],
    }


@app.get("/bookings")
async def bookings(
    property_id: str = Query(..., description="Tenant property ID"),
    limit: int = Query(50, ge=1, le=200),
):
    """Tenant-scoped bookings (RLS enforced)."""
    rows = await tenant_fetch(
        property_id,
        """SELECT booking_id, property_id, room_type, checkin, checkout,
                  status, amount_inr, source, created_at
           FROM bookings
           WHERE property_id = $1
           ORDER BY created_at DESC
           LIMIT $2""",
        property_id, limit,
    )
    return {
        "property_id": property_id,
        "items": [
            {
                "booking_id": r["booking_id"],
                "room_type": r["room_type"],
                "checkin": r["checkin"].isoformat() if r["checkin"] else None,
                "checkout": r["checkout"].isoformat() if r["checkout"] else None,
                "status": r["status"],
                "amount_inr": r["amount_inr"],
                "source": r["source"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ],
    }


@app.get("/messages")
async def messages(
    property_id: str = Query(..., description="Tenant property ID"),
    limit: int = Query(50, ge=1, le=200),
):
    """Tenant-scoped message logs."""
    rows = await tenant_fetch(
        property_id,
        """SELECT id, message_id, guest_id, text, intent, confidence, status, created_at
           FROM message_logs
           WHERE property_id = $1
           ORDER BY created_at DESC
           LIMIT $2""",
        property_id, limit,
    )
    return {
        "property_id": property_id,
        "items": [
            {
                "id": r["id"],
                "message_id": r["message_id"],
                "guest_id": r["guest_id"],
                "text": r["text"],
                "intent": r["intent"],
                "confidence": r["confidence"],
                "status": r["status"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ],
    }


# ── Part B: Data Assistant ────────────────────────────────────────────────────

@app.post("/ask", response_model=AskResponse)
async def ask(req: Ask):
    """
    Data question → NL→SQL (tenant-scoped, read-only, guarded).
    Product-help question → RAG over kb/ with citation.
    Unknown/hallucinated → refuse, don't fabricate.
    """
    # Verify property exists
    prop = await admin_fetch(
        "SELECT property_id FROM properties WHERE property_id = $1", req.property_id
    )
    if not prop:
        raise HTTPException(404, f"Property {req.property_id!r} not found")

    if is_product_question(req.question):
        # RAG path
        result = await rag_answer(req.question)
        return AskResponse(
            answer=result["answer"],
            sql=None,
            rows=[],
            source=result.get("source"),
            type=result.get("type", "rag"),
        )
    else:
        # NL → SQL path
        try:
            result = await execute_nl_query(req.question, req.property_id)
            return AskResponse(
                answer=result["answer"],
                sql=result["sql"],
                rows=result["rows"],
                source=None,
                type="data",
            )
        except SQLGuardError as e:
            logger.warning("SQL blocked for property=%s: %s", req.property_id, e)
            return AskResponse(
                answer=f"Query blocked for safety: {e}",
                sql=None,
                rows=[],
                type="blocked",
            )
        except Exception as exc:
            logger.error("ask error: %s", exc)
            return AskResponse(
                answer="Technical error processing your question.",
                sql=None,
                rows=[],
                type="error",
            )
