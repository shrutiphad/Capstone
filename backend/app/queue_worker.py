"""
Async queue worker for side-effects.
POST /message returns immediately after enqueuing.
Worker processes jobs async, including OTA push with retry/backoff.

OTA endpoints (mock_ota_server.py on :9000):
  GET  /rates?property_id=&page=   — paginated rates (for reading)
  POST /availability               — push availability update (idempotent on push_id)
"""
import asyncio
import json
import logging
import time
import uuid
import aiohttp

from .config import get_settings
from .database import admin_execute

logger = logging.getLogger(__name__)

_queue: asyncio.Queue = asyncio.Queue()


async def enqueue(job_type: str, payload: dict) -> None:
    """Enqueue a side-effect job. Non-blocking."""
    await _queue.put({"type": job_type, "payload": payload})


async def emit_event(property_id: str, event_type: str, payload: dict) -> None:
    """Persist an event row (bypasses RLS — worker has full context)."""
    try:
        await admin_execute(
            "INSERT INTO events(property_id, event_type, payload) VALUES($1, $2, $3)",
            property_id,
            event_type,
            json.dumps(payload),
        )
    except Exception as exc:
        logger.error("emit_event failed: %s", exc)


# ── OTA integration ───────────────────────────────────────────────────────────

async def _fetch_ota_rates(property_id: str) -> list[dict]:
    """Fetch paginated rates from mock OTA with retry. Returns all pages."""
    settings = get_settings()
    all_rates = []
    page = 0
    while True:
        url = f"{settings.OTA_URL}/rates"
        params = {"property_id": property_id, "page": page}
        for attempt in range(settings.OTA_MAX_RETRIES):
            delay = min(2 ** attempt, 30)
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            all_rates.extend(data.get("rates", []))
                            next_page = data.get("next_page")
                            if next_page is None:
                                return all_rates
                            page = next_page
                            break  # go to next page
                        elif resp.status == 429:
                            retry_after = int(resp.headers.get("Retry-After", delay))
                            logger.warning("OTA GET /rates 429 — retry in %ds", retry_after)
                            await asyncio.sleep(retry_after)
                        else:
                            logger.warning("OTA GET /rates %d attempt=%d", resp.status, attempt + 1)
                            await asyncio.sleep(delay)
            except Exception as exc:
                logger.warning("OTA rates fetch error attempt=%d: %s", attempt + 1, exc)
                await asyncio.sleep(delay)
        else:
            logger.error("OTA GET /rates failed after %d attempts", settings.OTA_MAX_RETRIES)
            return all_rates  # return what we have


async def _push_ota_availability(property_id: str, booking_id: str) -> None:
    """POST availability to mock OTA with retry/backoff. Idempotent on push_id."""
    settings = get_settings()
    push_id = f"{property_id}_{booking_id}"
    url = f"{settings.OTA_URL}/availability"
    body = {"property_id": property_id, "booking_id": booking_id, "push_id": push_id}

    for attempt in range(settings.OTA_MAX_RETRIES):
        delay = min(2 ** attempt, 30)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        logger.info("OTA push ok: push_id=%s status=%s", push_id, data.get("status"))
                        await emit_event(
                            property_id, "ota_push_ok",
                            {"push_id": push_id, "attempt": attempt + 1, "status": data.get("status")}
                        )
                        return
                    elif resp.status == 429:
                        retry_after = int(resp.headers.get("Retry-After", delay))
                        logger.warning("OTA POST 429 push_id=%s — retry in %ds", push_id, retry_after)
                        await asyncio.sleep(retry_after)
                        continue
                    else:
                        logger.warning("OTA POST %d push_id=%s attempt=%d", resp.status, push_id, attempt + 1)
        except Exception as exc:
            logger.warning("OTA push error attempt=%d: %s", attempt + 1, exc)

        if attempt < settings.OTA_MAX_RETRIES - 1:
            await asyncio.sleep(delay)

    logger.error("OTA push failed after %d attempts push_id=%s", settings.OTA_MAX_RETRIES, push_id)
    await emit_event(property_id, "ota_push_failed", {"push_id": push_id, "attempts": settings.OTA_MAX_RETRIES})


# ── Workflow handlers ─────────────────────────────────────────────────────────

async def _handle_booking(payload: dict) -> None:
    pid = payload["property_id"]
    msg_id = payload["message_id"]
    text = payload.get("text", "")

    booking_id = f"bk_{uuid.uuid4().hex[:8]}"
    try:
        await admin_execute(
            """INSERT INTO bookings(booking_id, property_id, room_type, checkin, checkout,
                                    status, amount_inr, source)
               VALUES($1,$2,$3,CURRENT_DATE,CURRENT_DATE+1,'pending_confirmation',0,'direct')
               ON CONFLICT DO NOTHING""",
            booking_id, pid, "standard",
        )
        await emit_event(pid, "booking_created", {"booking_id": booking_id, "message_id": msg_id})
        # Bonus: fetch OTA rates then push availability
        await _fetch_ota_rates(pid)
        await _push_ota_availability(pid, booking_id)
    except Exception as exc:
        logger.error("booking_workflow error: %s", exc)
        await emit_event(pid, "booking_error", {"error": str(exc), "message_id": msg_id})


async def _handle_cancellation(payload: dict) -> None:
    pid = payload["property_id"]
    msg_id = payload["message_id"]
    await emit_event(pid, "cancellation_requested", {"message_id": msg_id, "text": payload.get("text", "")})


async def _handle_faq(payload: dict) -> None:
    pid = payload["property_id"]
    msg_id = payload["message_id"]
    await emit_event(pid, "faq_handled", {"message_id": msg_id})


async def _handle_complaint(payload: dict) -> None:
    pid = payload["property_id"]
    msg_id = payload["message_id"]
    await emit_event(pid, "complaint_logged", {"message_id": msg_id, "text": payload.get("text", "")})


async def _handle_wakeup(payload: dict) -> None:
    pid = payload["property_id"]
    msg_id = payload["message_id"]
    await emit_event(pid, "wakeup_scheduled", {"message_id": msg_id})


async def _handle_handoff(payload: dict) -> None:
    pid = payload["property_id"]
    await emit_event(
        pid, "human_handoff",
        {
            "message_id": payload["message_id"],
            "text": payload.get("text", ""),
            "confidence": payload.get("confidence"),
            "intent": payload.get("intent"),
            "note": payload.get("note", ""),
        }
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
    """Background worker — runs indefinitely."""
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
            logger.info("Queue worker stopped")
            break
        except Exception as exc:
            logger.error("Worker unhandled error: %s", exc)
            _queue.task_done()
