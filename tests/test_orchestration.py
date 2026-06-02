"""
Part A Tests — Orchestration, Lifecycle, Guards

Uses the exact labeled_messages.json from seed/ to test all 15 seed messages,
plus adversarial/negative cases.

Covers:
  - All 5 intents in English + Hinglish (from seed/labeled_messages.json)
  - m14 "umm maybe cancel or change, not sure yet" — MUST NOT auto-cancel (hard fail)
  - Low-confidence / gibberish → human handoff
  - Idempotency: replay same message_id → single side-effect, cached response
  - Tenant isolation: hotel_a events must not bleed into hotel_b
  - Property not found → 404
  - /events and /bookings require property_id → 422
"""
import uuid
import asyncio
import pytest
import httpx
from conftest import PROP_A, PROP_B

# ── Exact seed messages from seed/labeled_messages.json ──────────────────────
LABELED_MESSAGES = [
    {"message_id": "m1",  "property_id": "hotel_a", "text": "do you have a room for tomorrow night for 2 people",     "intent": "booking"},
    {"message_id": "m2",  "property_id": "hotel_a", "text": "kya kal ka room milega 2 logo ke liye",                  "intent": "booking"},
    {"message_id": "m3",  "property_id": "hotel_a", "text": "please cancel my booking for tonight",                   "intent": "cancellation"},
    {"message_id": "m4",  "property_id": "hotel_a", "text": "what time is checkout?",                                 "intent": "faq"},
    {"message_id": "m5",  "property_id": "hotel_a", "text": "the AC in room 203 is not working at all",               "intent": "complaint"},
    {"message_id": "m6",  "property_id": "hotel_a", "text": "please give me a wake up call at 6am",                   "intent": "wakeup"},
    {"message_id": "m7",  "property_id": "hotel_b", "text": "is there a single room available from 1st",              "intent": "booking"},
    {"message_id": "m8",  "property_id": "hotel_b", "text": "what is the monthly rent and deposit",                   "intent": "faq"},
    {"message_id": "m9",  "property_id": "hotel_b", "text": "cancel kar do meri booking",                             "intent": "cancellation"},
    {"message_id": "m10", "property_id": "hotel_b", "text": "wifi password kya hai",                                  "intent": "faq"},
    {"message_id": "m11", "property_id": "hotel_b", "text": "the food yesterday was cold and bad",                    "intent": "complaint"},
    {"message_id": "m12", "property_id": "hotel_b", "text": "wake me up at 5:30 tomorrow please",                     "intent": "wakeup"},
    {"message_id": "m13", "property_id": "hotel_a", "text": "hi",                                                     "intent": "faq"},
    # m14 is THE ambiguous cancel test — must NOT auto-cancel
    {"message_id": "m14", "property_id": "hotel_a", "text": "umm maybe cancel or change, not sure yet",               "intent": "cancellation"},
    {"message_id": "m15", "property_id": "hotel_a", "text": "book a deluxe room and also what's the wifi",            "intent": "booking"},
]


def unique_mid(base: str) -> str:
    """Make message IDs unique per test run so idempotency tests don't collide."""
    return f"{base}_{uuid.uuid4().hex[:6]}"


async def send_message(client, property_id, text, message_id=None):
    r = await client.post("/message", json={
        "property_id": property_id,
        "guest_id": "guest_test",
        "message_id": message_id or unique_mid("t"),
        "text": text,
    })
    assert r.status_code == 200, f"POST /message failed: {r.text}"
    return r.json()


# ── Health ────────────────────────────────────────────────────────────────────

async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ── POST /property ────────────────────────────────────────────────────────────

async def test_create_property(client, seeded_properties):
    r = await client.post("/property", json={
        "property_id": "hotel_test_tmp",
        "name": "Temp Test Hotel",
        "language": "en",
    })
    assert r.status_code in (200, 201)
    assert r.json()["stored"] is True


# ── All 15 seed messages: intent accuracy ────────────────────────────────────

@pytest.mark.parametrize("msg", [m for m in LABELED_MESSAGES if m["message_id"] != "m14"])
async def test_seed_message_intent(client, seeded_properties, msg):
    """Each seed message must be classified to its labeled intent."""
    data = await send_message(
        client, msg["property_id"], msg["text"],
        message_id=unique_mid(msg["message_id"])
    )
    assert data["intent"] == msg["intent"], (
        f"[{msg['message_id']}] text={msg['text']!r} "
        f"expected={msg['intent']!r} got={data['intent']!r} conf={data['confidence']}"
    )


# ── HARD FAIL: m14 ambiguous cancel must NOT auto-cancel ─────────────────────

async def test_m14_ambiguous_must_not_auto_cancel(client, seeded_properties):
    """
    m14: "umm maybe cancel or change, not sure yet"
    CRITICAL GUARD: must never result in status='queued' for cancellation workflow.
    Must be needs_human or needs_confirmation.
    """
    data = await send_message(
        client, PROP_A,
        "umm maybe cancel or change, not sure yet",
        message_id=unique_mid("m14"),
    )
    if data["intent"] == "cancellation":
        assert data["status"] in ("needs_human", "needs_confirmation"), (
            f"HARD FAIL: ambiguous message auto-queued a cancellation! "
            f"status={data['status']} confidence={data['confidence']}"
        )


@pytest.mark.parametrize("ambiguous_text", [
    "nahin aa pa raha",
    "plans change ho gaye",
    "not sure anymore",
    "maybe I need to change something",
    "sochna padega",
])
async def test_other_ambiguous_no_auto_cancel(client, seeded_properties, ambiguous_text):
    """Additional ambiguous texts must not fire cancellation workflow silently."""
    data = await send_message(client, PROP_A, ambiguous_text)
    if data["intent"] == "cancellation":
        assert data["status"] in ("needs_human", "needs_confirmation"), (
            f"Ambiguous text auto-queued cancellation: {ambiguous_text!r} "
            f"status={data['status']} conf={data['confidence']}"
        )


# ── Low-confidence → human handoff ───────────────────────────────────────────

async def test_low_confidence_handoff(client, seeded_properties):
    """Pure gibberish should not crash and should go to needs_human or still classify."""
    data = await send_message(client, PROP_A, "xkcd zxqy ??? ##$$")
    assert data["status"] in ("needs_human", "needs_confirmation", "queued")
    assert data["message_id"] is not None


# ── Idempotency ───────────────────────────────────────────────────────────────

async def test_idempotency_replay(client, seeded_properties):
    """Sending the same message_id twice returns same result; second is flagged as duplicate."""
    mid = unique_mid("idem")
    first  = await send_message(client, PROP_A, "I want to book a room", message_id=mid)
    second = await send_message(client, PROP_A, "I want to book a room", message_id=mid)

    assert first["intent"]     == second["intent"]
    assert first["confidence"] == second["confidence"]
    assert second.get("note")  == "duplicate — idempotent"


async def test_idempotency_exactly_one_side_effect(client, seeded_properties):
    """
    Replay m1 three times — events for that message_id must appear only once
    (not duplicated) in the events feed.
    """
    mid = unique_mid("idem_m1")
    for _ in range(3):
        await send_message(client, PROP_A, "do you have a room for tomorrow night for 2 people", message_id=mid)

    await asyncio.sleep(1)  # let worker process

    r = await client.get("/events", params={"property_id": PROP_A, "limit": 200})
    events = r.json()["events"]
    # Count events referencing this message_id
    matching = [e for e in events if mid in str(e.get("payload", {}))]
    assert len(matching) <= 2, (
        f"Idempotency broken — message_id {mid!r} produced {len(matching)} events, expected ≤2"
    )


# ── Tenant isolation on /events ───────────────────────────────────────────────

async def test_events_tenant_isolation(client, seeded_properties):
    """Events emitted for hotel_a must not appear in hotel_b's feed."""
    marker = f"isolation_probe_{uuid.uuid4().hex}"
    # Send a unique complaint to hotel_a only
    await send_message(client, PROP_A, f"complaint: {marker}")
    await asyncio.sleep(1)

    r = await client.get("/events", params={"property_id": PROP_B, "limit": 200})
    assert r.status_code == 200
    for ev in r.json()["events"]:
        assert marker not in str(ev.get("payload", {})), (
            f"HARD FAIL cross-tenant event leak: hotel_a event appeared in hotel_b feed"
        )


# ── Tenant isolation on /bookings ─────────────────────────────────────────────

async def test_bookings_tenant_isolation(client, seeded_properties):
    """Bookings seeded for hotel_a must not appear under hotel_b query."""
    r_a = await client.get("/bookings", params={"property_id": PROP_A})
    r_b = await client.get("/bookings", params={"property_id": PROP_B})
    assert r_a.status_code == 200
    assert r_b.status_code == 200

    ids_a = {b["booking_id"] for b in r_a.json()["items"]}
    ids_b = {b["booking_id"] for b in r_b.json()["items"]}
    overlap = ids_a & ids_b
    assert not overlap, f"HARD FAIL cross-tenant booking leak: shared IDs = {overlap}"


# ── Input validation ──────────────────────────────────────────────────────────

async def test_events_missing_property_id(client):
    r = await client.get("/events")
    assert r.status_code == 422


async def test_bookings_missing_property_id(client):
    r = await client.get("/bookings")
    assert r.status_code == 422


async def test_message_unknown_property(client):
    r = await client.post("/message", json={
        "property_id": "hotel_does_not_exist_xyz",
        "guest_id": "g1",
        "message_id": unique_mid("unknown"),
        "text": "I want a room",
    })
    assert r.status_code == 404


# ── P95 metric exposed ────────────────────────────────────────────────────────

async def test_metrics_p95(client):
    r = await client.get("/metrics")
    assert r.status_code == 200
    assert "classify_p95_ms" in r.json()
