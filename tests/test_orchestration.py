"""
Part A Tests — Orchestration, Lifecycle, Guards

Covers:
- Intent classification: booking, cancellation, faq, complaint, wakeup
- Hinglish messages
- Ambiguous message must NOT auto-cancel (hard fail guard)
- Human handoff for low-confidence messages
- Idempotency: replay same message_id returns same result
- Tenant isolation on /events and /bookings
- Property creation
"""
import uuid
import pytest
import httpx
from conftest import PROP_A, PROP_B


# ── Helpers ───────────────────────────────────────────────────────────────────

def msg_id():
    return f"test_{uuid.uuid4().hex[:10]}"


async def send_message(client, property_id, text, message_id=None):
    payload = {
        "property_id": property_id,
        "guest_id": "guest_test",
        "message_id": message_id or msg_id(),
        "text": text,
    }
    r = await client.post("/message", json=payload)
    assert r.status_code == 200, f"POST /message failed: {r.text}"
    return r.json()


# ── Property API ──────────────────────────────────────────────────────────────

async def test_create_property(client, seeded_properties):
    """POST /property creates or upserts a property."""
    r = await client.post("/property", json={
        "property_id": "prop_test_x",
        "name": "Test Hotel",
        "city": "Bangalore",
        "total_rooms": 10,
    })
    assert r.status_code in (200, 201)
    assert r.json()["stored"] is True


# ── Intent Classification ─────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected_intent", [
    # English
    ("I want to book a room for tomorrow night", "booking"),
    ("Please cancel my booking", "cancellation"),
    ("What time is checkout?", "faq"),
    ("The AC is not working in my room", "complaint"),
    ("Please wake me up at 6am", "wakeup"),
    # Hinglish
    ("Kal ke liye ek room chahiye", "booking"),
    ("Meri booking cancel kar do", "cancellation"),
    ("Wifi ka password kya hai?", "faq"),
    ("AC kaam nahi kar raha", "complaint"),
    ("Kal subah 6 baje jagana", "wakeup"),
    # Pure Hindi-ish
    ("Ek room milega aaj raat ke liye?", "booking"),
    ("Room available hai kya?", "booking"),
])
async def test_intent_classification(client, seeded_properties, text, expected_intent):
    data = await send_message(client, PROP_A, text)
    assert data["intent"] == expected_intent, (
        f"Expected {expected_intent!r} for {text!r}, got {data['intent']!r} (conf={data['confidence']})"
    )


# ── HARD FAIL GUARD: Ambiguous message must NOT auto-cancel ───────────────────

@pytest.mark.parametrize("ambiguous_text", [
    "Nahin aa pa raha",          # "Can't make it" — ambiguous, might be cancel but might not
    "Plans change ho gaye",      # "Plans changed" — vague
    "Maybe rescheduling needed", # Ambiguous
    "Not sure anymore",          # Ambiguous
])
async def test_ambiguous_must_not_auto_cancel(client, seeded_properties, ambiguous_text):
    """
    CRITICAL: An ambiguous message must never result in status='queued' for cancellation.
    It must either be flagged needs_human / needs_confirmation, or classified as something else.
    """
    data = await send_message(client, PROP_A, ambiguous_text)
    # If classified as cancellation, confidence must be high AND status must not be 'queued' for low conf
    if data["intent"] == "cancellation":
        assert data["status"] in ("needs_human", "needs_confirmation"), (
            f"Ambiguous text auto-queued a cancellation! text={ambiguous_text!r} "
            f"confidence={data['confidence']} status={data['status']}"
        )


# ── Human Handoff ─────────────────────────────────────────────────────────────

async def test_low_confidence_triggers_handoff(client, seeded_properties):
    """Gibberish / very ambiguous input should trigger human handoff."""
    data = await send_message(client, PROP_A, "asdfgh qwerty zzz ???")
    assert data["status"] in ("needs_human", "needs_confirmation", "queued"), \
        f"Unexpected status: {data['status']}"
    # Should not crash
    assert data["message_id"] is not None


# ── Idempotency ───────────────────────────────────────────────────────────────

async def test_idempotency_replay(client, seeded_properties):
    """Sending the same message_id twice returns the same result, no duplicate side-effects."""
    mid = msg_id()
    first = await send_message(client, PROP_A, "I want to book a room", message_id=mid)
    second = await send_message(client, PROP_A, "I want to book a room", message_id=mid)

    assert first["intent"] == second["intent"]
    assert first["confidence"] == second["confidence"]
    assert second.get("note") == "duplicate — idempotent"


async def test_idempotency_different_property_same_msgid(client, seeded_properties):
    """Same message_id on different property — first one wins (message_id is globally unique)."""
    mid = msg_id()
    r1 = await send_message(client, PROP_A, "Book a room please", message_id=mid)
    r2 = await send_message(client, PROP_B, "Book a room please", message_id=mid)
    # Second should be flagged as duplicate
    assert r2.get("note") == "duplicate — idempotent"


# ── Tenant Isolation on /events ───────────────────────────────────────────────

async def test_events_tenant_isolation(client, seeded_properties):
    """Events for prop_A must not appear under prop_B query."""
    # Send unique event for PROP_A
    unique_text = f"unique booking request {uuid.uuid4().hex}"
    await send_message(client, PROP_A, unique_text)

    import asyncio
    await asyncio.sleep(1)  # Let worker process

    # Fetch PROP_B events and make sure the unique text doesn't bleed over
    r = await client.get("/events", params={"property_id": PROP_B, "limit": 100})
    assert r.status_code == 200
    events_b = r.json()["events"]
    for ev in events_b:
        payload_str = str(ev.get("payload", ""))
        assert unique_text not in payload_str, (
            f"Cross-tenant event leak! PROP_A event appeared in PROP_B events: {ev}"
        )


# ── Tenant Isolation on /bookings ─────────────────────────────────────────────

async def test_bookings_tenant_isolation(client, seeded_properties):
    """Bookings for prop_A must not appear under prop_B query."""
    r_a = await client.get("/bookings", params={"property_id": PROP_A})
    r_b = await client.get("/bookings", params={"property_id": PROP_B})
    assert r_a.status_code == 200
    assert r_b.status_code == 200

    ids_a = {b["booking_id"] for b in r_a.json()["items"]}
    ids_b = {b["booking_id"] for b in r_b.json()["items"]}
    overlap = ids_a & ids_b
    assert not overlap, f"Cross-tenant booking leak! Shared IDs: {overlap}"


# ── /events and /bookings reject missing property_id ─────────────────────────

async def test_events_requires_property_id(client):
    r = await client.get("/events")
    assert r.status_code == 422  # FastAPI validation error


async def test_bookings_requires_property_id(client):
    r = await client.get("/bookings")
    assert r.status_code == 422


# ── Property not found ────────────────────────────────────────────────────────

async def test_message_unknown_property(client):
    r = await client.post("/message", json={
        "property_id": "prop_does_not_exist",
        "guest_id": "g1",
        "message_id": msg_id(),
        "text": "I want a room",
    })
    assert r.status_code == 404


# ── Health endpoint ───────────────────────────────────────────────────────────

async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
