"""
Seeds the database from seed/ directory.
properties.json has: property_id, name, language, custom_faqs (no city/total_rooms).
data.sql has the actual HMS data for hotel_a and hotel_b.
"""
import json
import logging
from pathlib import Path

from .database import admin_execute, admin_fetch

logger = logging.getLogger(__name__)

SEED_DIR = Path(__file__).parent.parent / "seed"


async def seed_properties() -> None:
    """Load properties from properties.json and upsert into DB."""
    props_file = SEED_DIR / "properties.json"
    if not props_file.exists():
        logger.warning("properties.json not found at %s", props_file)
        return

    with open(props_file) as f:
        properties = json.load(f)

    for prop in properties:
        pid = prop["property_id"]
        existing = await admin_fetch(
            "SELECT property_id FROM properties WHERE property_id = $1", pid
        )
        if existing:
            logger.debug("Property %s already exists, skipping", pid)
            continue

        config = json.dumps({
            "language": prop.get("language", "en"),
            "custom_faqs": prop.get("custom_faqs", []),
        })
        await admin_execute(
            """INSERT INTO properties(property_id, name, config)
               VALUES($1, $2, $3)
               ON CONFLICT(property_id) DO NOTHING""",
            pid,
            prop.get("name", pid),
            config,
        )
        logger.info("Seeded property: %s", pid)


async def seed_hms_data() -> None:
    """Run seed/data.sql to insert rooms, rates, bookings."""
    data_file = SEED_DIR / "data.sql"
    if not data_file.exists():
        logger.warning("data.sql not found at %s", data_file)
        return

    sql_text = data_file.read_text()
    statements = [s.strip() for s in sql_text.split(";") if s.strip() and not s.strip().startswith("--")]
    for stmt in statements:
        if not stmt:
            continue
        try:
            await admin_execute(stmt)
        except Exception as exc:
            err = str(exc).lower()
            if "duplicate" in err or "already exists" in err or "unique" in err:
                pass  # already seeded
            else:
                logger.warning("Seed stmt failed: %s | %s", exc, stmt[:100])

    logger.info("HMS data seeded from data.sql")


async def run_seed() -> None:
    await seed_properties()
    await seed_hms_data()
    logger.info("Seeding complete")
