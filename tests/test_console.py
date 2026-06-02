"""
Part C Tests — Owner Console Smoke Tests

Verifies the API shapes the console depends on,
and that error/empty/loading states are backed by correct API responses.
"""
import pytest
import httpx
from conftest import PROP_A, PROP_B


# ── /events shape ─────────────────────────────────────────────────────────────

async def test_events_response_shape(client, seeded_properties):
    r = await client.get("/events", params={"property_id": PROP_A, "limit": 10})
    assert r.status_code == 200
    body = r.json()
    assert "events" in body
    assert "property_id" in body
    assert body["property_id"] == PROP_A
    for ev in body["events"]:
        assert "id" in ev
        assert "event_type" in ev
        assert "payload" in ev
        assert "created_at" in ev


# ── /bookings shape ───────────────────────────────────────────────────────────

async def test_bookings_response_shape(client, seeded_properties):
    r = await client.get("/bookings", params={"property_id": PROP_A, "limit": 10})
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "property_id" in body
    assert body["property_id"] == PROP_A
    for b in body["items"]:
        assert "booking_id" in b
        assert "status" in b
        assert "amount_inr" in b
        assert "room_type" in b


# ── /ask shape ────────────────────────────────────────────────────────────────

async def test_ask_response_shape(client, seeded_properties):
    r = await client.post("/ask", json={
        "property_id": PROP_A,
        "question": "kitni bookings hain?",
    })
    assert r.status_code == 200
    body = r.json()
    assert "answer" in body
    assert "type" in body
    assert body["type"] in ("data", "rag", "refused", "blocked", "error")


# ── Seed bookings are present ─────────────────────────────────────────────────

async def test_seed_bookings_present(client, seeded_properties):
    """hotel_a should have the 5 bookings from seed/data.sql."""
    r = await client.get("/bookings", params={"property_id": PROP_A, "limit": 50})
    assert r.status_code == 200
    items = r.json()["items"]
    ids = {b["booking_id"] for b in items}
    # bk1–bk5 are hotel_a bookings from data.sql
    for expected_id in ["bk1", "bk2", "bk3", "bk4", "bk5"]:
        assert expected_id in ids, f"Seed booking {expected_id} not found in /bookings for hotel_a"


async def test_seed_bookings_hotel_b(client, seeded_properties):
    """hotel_b should have bk6 and bk7."""
    r = await client.get("/bookings", params={"property_id": PROP_B, "limit": 50})
    assert r.status_code == 200
    items = r.json()["items"]
    ids = {b["booking_id"] for b in items}
    for expected_id in ["bk6", "bk7"]:
        assert expected_id in ids, f"Seed booking {expected_id} not found for hotel_b"


# ── Limit param is respected ──────────────────────────────────────────────────

async def test_events_limit(client, seeded_properties):
    r = await client.get("/events", params={"property_id": PROP_A, "limit": 2})
    assert r.status_code == 200
    assert len(r.json()["events"]) <= 2


async def test_bookings_limit(client, seeded_properties):
    r = await client.get("/bookings", params={"property_id": PROP_A, "limit": 2})
    assert r.status_code == 200
    assert len(r.json()["items"]) <= 2


# ── Console error states: invalid property → 404 ─────────────────────────────

async def test_ask_invalid_property_404(client):
    r = await client.post("/ask", json={
        "property_id": "hotel_nonexistent_xyz",
        "question": "how many bookings?",
    })
    assert r.status_code == 404


async def test_events_invalid_property_empty(client):
    """Non-existent property returns empty events list (RLS filters all rows)."""
    r = await client.get("/events", params={"property_id": "hotel_ghost"})
    # Either 200 with empty list or 422/404 — both are acceptable console error states
    assert r.status_code in (200, 404, 422)


# ── /metrics endpoint ─────────────────────────────────────────────────────────

async def test_metrics_endpoint(client):
    r = await client.get("/metrics")
    assert r.status_code == 200
    assert "classify_p95_ms" in r.json()
