"""
Seeds the database from seed/ directory.
Run once on startup or explicitly.
"""
import json
import logging
from pathlib import Path

from .database import admin_execute, admin_fetch

logger = logging.getLogger(__name__)

SEED_DIR = Path(__file__).parent.parent / "seed"


async def seed_properties() -> None:
    """Load properties from properties.json if not already present."""
    props_file = SEED_DIR / "properties.json"
    if not props_file.exists():
        logger.warning("properties.json not found at %s", props_file)
        return

    with open(props_file) as f:
        properties = json.load(f)

    for prop in properties:
        existing = await admin_fetch(
            "SELECT property_id FROM properties WHERE property_id = $1",
            prop["property_id"],
        )
        if existing:
            logger.debug("Property %s already exists, skipping", prop["property_id"])
            continue

        config = {
            "language": prop.get("language", "en"),
            "custom_faqs": prop.get("custom_faqs", []),
        }
        await admin_execute(
            """INSERT INTO properties(property_id, name, city, total_rooms, config)
               VALUES($1, $2, $3, $4, $5)
               ON CONFLICT DO NOTHING""",
            prop["property_id"],
            prop.get("name", ""),
            prop.get("city", ""),
            prop.get("total_rooms", 0),
            json.dumps(config),
        )
        logger.info("Seeded property: %s", prop["property_id"])


async def seed_hms_data() -> None:
    """Run seed/data.sql to insert rooms, rates, bookings."""
    data_file = SEED_DIR / "data.sql"
    if not data_file.exists():
        return

    sql_text = data_file.read_text()

    # Split on semicolons (simple approach)
    statements = [s.strip() for s in sql_text.split(";") if s.strip()]
    for stmt in statements:
        if stmt.startswith("--") or not stmt:
            continue
        try:
            await admin_execute(stmt)
        except Exception as exc:
            # Ignore duplicate key errors (re-seeding)
            if "duplicate" in str(exc).lower() or "already exists" in str(exc).lower():
                pass
            else:
                logger.warning("Seed stmt failed: %s | %s", exc, stmt[:80])

    logger.info("HMS data seeded from data.sql")


async def run_seed() -> None:
    await seed_properties()
    await seed_hms_data()
    logger.info("Seeding complete")
