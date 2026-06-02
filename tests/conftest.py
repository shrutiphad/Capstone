"""
Shared test fixtures.
Property IDs match seed/data.sql and seed/properties.json exactly:
  hotel_a — Hotel Surya, Varanasi
  hotel_b — Coastal Stay PG, Bengaluru
"""
import os
import asyncio
import pytest
import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")

PROP_A = "hotel_a"
PROP_B = "hotel_b"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# @pytest.fixture(scope="session")
# async def client():
#     async with AsyncClient(app=app, base_url=BASE_URL, timeout=30.0) as client:
#         yield c
@pytest.fixture(scope="session")
async def client():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as c:
        yield c

# @pytest.fixture(scope="session")
# async def seeded_properties(client: httpx.AsyncClient):
@pytest.fixture(scope="session")
async def seeded_properties(client):
    """Ensure both seed properties exist before running tests."""
    for prop in [
        {
            "property_id": PROP_A,
            "name": "Hotel Surya (Varanasi)",
            "language": "hi",
            "custom_faqs": [
                {"q": "checkout time", "a": "11 AM"},
                {"q": "wifi", "a": "Free WiFi, password at reception"},
                {"q": "parking", "a": "Free on-site parking"},
            ],
        },
        {
            "property_id": PROP_B,
            "name": "Coastal Stay PG (Bengaluru)",
            "language": "en",
            "custom_faqs": [
                {"q": "rent", "a": "₹9,500/month sharing, ₹14,000 single"},
                {"q": "food", "a": "Veg/non-veg mess included"},
                {"q": "deposit", "a": "Two months refundable"},
            ],
        },
    ]:
        r = await client.post("/property", json=prop)
        assert r.status_code in (200, 201), f"Seed property failed: {r.text}"
    return PROP_A, PROP_B
