"""
In-process async queue for side-effects.
POST /message returns immediately after enqueuing.
This worker processes jobs asynchronously.

Job types:
  - booking_workflow
  - cancellation_workflow
  - faq_workflow
  - complaint_workflow
  - wakeup_workflow
"""
import asyncio
import json
import logging
import time
import uuid
import aiohttp

from .config import get_settings
from .database import tenant_execute, admin_execute

logger = logging.getLogger(__name__)

_queue: asyncio.Queue = asyncio.Queue()
_running = False


async def enqueue(job_type: str, payload: dict) -> None:
    """Enqueue a side-effect job. Non-blocking."""
    await _queue.put({"type": job_type, "payload": payload})


async def emit_event(property_id: str, event_type: str, payload: dict) -> None:
    """Persist an event row, bypassing RLS (worker has full access)."""
    try:
        await admin_execute(
            "INSERT INTO events(property_id, event_type, payload) VALUES($1, $2, $3)",
            property_id,
            event_type,
            json.dumps(payload),
        )
    except Exception as exc:
        logger.error("emit_event failed: %s", exc)


# ── Workflow handlers ───────────────────────────────────────────────────────

async def _handle_booking(payload: dict) -> None:
    pid = payload["property_id"]
    msg_id = payload["message_id"]
    text = payload["text"]

    booking_id = f"bk_{uuid.uuid4().hex[:8]}"
    try:
        await admin_execute(
            """INSERT INTO bookings(booking_id, property_id, room_type, checkin, checkout, status, amount_inr, source)
               VALUES($1,$2,$3,$4,$5,$6,$7,$8)
               ON CONFLICT DO NOTHING""",
            booking_id, pid, "standard",
            "2026-06-01", "2026-06-02",  # placeholder — real impl would parse from text
            "pending_confirmation", 1800, "direct",
        )
        await emit_event(pid, "booking_created", {"booking_id": booking_id, "message_id": msg_id, "text": text})

        # OTA push (bonus)
        await _push_ota(pid, booking_id)
    except Exception as exc:
        logger.error("booking_workflow error: %s", exc)
        await emit_event(pid, "booking_error", {"error": str(exc), "message_id": msg_id})


async def _push_ota(property_id: str, booking_id: str) -> None:
    """Push availability to mock OTA with retry/backoff + idempotency."""
    settings = get_settings()
    push_id = f"{property_id}_{booking_id}"
    url = f"{settings.OTA_URL}/availability"
    body = {"property_id": property_id, "booking_id": booking_id, "push_id": push_id}

    for attempt in range(settings.OTA_MAX_RETRIES):
        delay = min(2 ** attempt, 30)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        logger.info("OTA push ok: push_id=%s status=%s", push_id, data.get("status"))
                        await emit_event(
                            property_id, "ota_push_ok",
                            {"push_id": push_id, "attempt": attempt + 1, "status": data.get("status")}
                        )
                        return
                    elif resp.status == 429:
                        retry_after = int(resp.headers.get("Retry-After", delay))
                        logger.warning("OTA 429 push_id=%s, retry in %ds", push_id, retry_after)
                        await asyncio.sleep(retry_after)
                        continue
                    else:
                        logger.warning("OTA %d push_id=%s attempt=%d", resp.status, push_id, attempt + 1)
        except Exception as exc:
            logger.warning("OTA push error attempt=%d: %s", attempt + 1, exc)

        if attempt < settings.OTA_MAX_RETRIES - 1:
            await asyncio.sleep(delay)

    logger.error("OTA push failed after %d attempts push_id=%s", settings.OTA_MAX_RETRIES, push_id)
    await emit_event(property_id, "ota_push_failed", {"push_id": push_id, "attempts": settings.OTA_MAX_RETRIES})


async def _handle_cancellation(payload: dict) -> None:
    pid = payload["property_id"]
    msg_id = payload["message_id"]
    # Note: we only reach here if confidence > CANCEL_CONFIDENCE_THRESHOLD
    await emit_event(pid, "cancellation_requested", {"message_id": msg_id, "text": payload["text"]})
    logger.info("cancellation_workflow pid=%s msg=%s", pid, msg_id)


async def _handle_faq(payload: dict) -> None:
    pid = payload["property_id"]
    msg_id = payload["message_id"]
    await emit_event(pid, "faq_handled", {"message_id": msg_id, "text": payload["text"]})


async def _handle_complaint(payload: dict) -> None:
    pid = payload["property_id"]
    msg_id = payload["message_id"]
    await emit_event(pid, "complaint_logged", {"message_id": msg_id, "text": payload["text"]})


async def _handle_wakeup(payload: dict) -> None:
    pid = payload["property_id"]
    msg_id = payload["message_id"]
    await emit_event(pid, "wakeup_scheduled", {"message_id": msg_id, "text": payload["text"]})


async def _handle_handoff(payload: dict) -> None:
    pid = payload["property_id"]
    msg_id = payload["message_id"]
    await emit_event(
        pid, "human_handoff",
        {"message_id": msg_id, "text": payload["text"], "confidence": payload.get("confidence"), "intent": payload.get("intent")}
    )


WORKFLOW_HANDLERS = {
    "booking_workflow":      _handle_booking,
    "cancellation_workflow": _handle_cancellation,
    "faq_workflow":          _handle_faq,
    "complaint_workflow":    _handle_complaint,
    "wakeup_workflow":       _handle_wakeup,
    "handoff_workflow":      _handle_handoff,
}


async def worker() -> None:
    """Background worker — runs indefinitely, consuming from the queue."""
    global _running
    _running = True
    logger.info("Queue worker started")
    while True:
        try:
            job = await _queue.get()
            job_type = job.get("type", "")
            handler = WORKFLOW_HANDLERS.get(job_type)
            if handler:
                await handler(job["payload"])
            else:
                logger.warning("Unknown job type: %s", job_type)
            _queue.task_done()
        except asyncio.CancelledError:
            logger.info("Queue worker cancelled")
            break
        except Exception as exc:
            logger.error("Worker error: %s", exc)
            _queue.task_done()
