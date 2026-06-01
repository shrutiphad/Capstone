"""
Part C Tests — Owner Console Smoke Tests

These are backend smoke tests that verify:
- The APIs the console depends on all return valid shapes
- Events endpoint returns the right structure
- Bookings endpoint returns the right structure
- Ask endpoint returns the right structure

For full browser-level tests, Playwright would be used (see TESTING.md).
"""
import pytest
import httpx
from conftest import PROP_A


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


async def test_bookings_response_shape(client, seeded_properties):
    r = await client.get("/bookings", params={"property_id": PROP_A, "limit": 10})
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "property_id" in body
    for b in body["items"]:
        assert "booking_id" in b
        assert "status" in b
        assert "amount_inr" in b


async def test_ask_response_shape(client, seeded_properties):
    r = await client.post("/ask", json={
        "property_id": PROP_A,
        "question": "Kitni bookings hain?",
    })
    assert r.status_code == 200
    body = r.json()
    assert "answer" in body
    assert "type" in body
    assert body["type"] in ("data", "rag", "refused", "blocked", "error")


async def test_events_limit_respected(client, seeded_properties):
    r = await client.get("/events", params={"property_id": PROP_A, "limit": 3})
    assert r.status_code == 200
    assert len(r.json()["events"]) <= 3


async def test_bookings_limit_respected(client, seeded_properties):
    r = await client.get("/bookings", params={"property_id": PROP_A, "limit": 3})
    assert r.status_code == 200
    assert len(r.json()["items"]) <= 3


async def test_metrics_endpoint(client):
    r = await client.get("/metrics")
    assert r.status_code == 200
    body = r.json()
    assert "classify_p95_ms" in body
