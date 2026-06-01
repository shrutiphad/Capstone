"""
Shared test fixtures.
Uses httpx.AsyncClient against the live backend.
Set BASE_URL env var to point at a local or deployed backend.
"""
import os
import asyncio
import pytest
import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")

# Two test properties for isolation tests
PROP_A = "prop_001"
PROP_B = "prop_002"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def client():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as c:
        yield c


@pytest.fixture(scope="session")
async def seeded_properties(client: httpx.AsyncClient):
    """Ensure both test properties exist before running tests."""
    for prop in [
        {"property_id": PROP_A, "name": "Hotel Sunrise Delhi", "city": "Delhi", "total_rooms": 50},
        {"property_id": PROP_B, "name": "Hotel Pearl Mumbai", "city": "Mumbai", "total_rooms": 30},
    ]:
        r = await client.post("/property", json=prop)
        assert r.status_code in (200, 201), f"Seed property failed: {r.text}"
    return PROP_A, PROP_B
