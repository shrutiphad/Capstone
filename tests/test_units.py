"""
Unit Tests — No network, no DB required.

Tests:
- classify.py: rule-based stage 1 (offline, no LLM)
- nl_sql.py: _validate_sql guard
- rag.py: is_product_question heuristic
"""
import pytest
import sys
import os

# Add backend to path so we can import directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.classify import _rule_classify
from app.nl_sql import _validate_sql, SQLGuardError
from app.rag import is_product_question


# ── Rule-based classifier unit tests ─────────────────────────────────────────

class TestRuleClassifier:
    def test_booking_english(self):
        intent, conf = _rule_classify("I want to book a room for tonight")
        assert intent == "booking"
        assert conf > 0.5

    def test_booking_hinglish(self):
        intent, conf = _rule_classify("Ek room chahiye kal ke liye")
        assert intent == "booking"

    def test_cancellation(self):
        intent, conf = _rule_classify("Please cancel my booking")
        assert intent == "cancellation"

    def test_faq_wifi(self):
        intent, conf = _rule_classify("What is the wifi password?")
        assert intent == "faq"

    def test_complaint(self):
        intent, conf = _rule_classify("AC not working in my room, terrible service")
        assert intent == "complaint"

    def test_wakeup(self):
        intent, conf = _rule_classify("Please wake me up at 6am tomorrow")
        assert intent == "wakeup"

    def test_wakeup_hinglish(self):
        intent, conf = _rule_classify("Kal subah 6 baje jagana")
        assert intent == "wakeup"

    def test_empty_returns_none(self):
        intent, conf = _rule_classify("")
        assert intent is None
        assert conf == 0.0

    def test_gibberish_returns_none(self):
        intent, conf = _rule_classify("asdfgh qwerty 12345")
        assert intent is None or conf < 0.5


# ── SQL Guard unit tests ──────────────────────────────────────────────────────

class TestSQLGuard:
    def test_valid_select(self):
        sql = "SELECT COUNT(*) FROM bookings WHERE status = 'confirmed'"
        result = _validate_sql(sql)
        assert "SELECT" in result.upper()

    def test_rejects_insert(self):
        with pytest.raises(SQLGuardError, match="Only SELECT"):
            _validate_sql("INSERT INTO bookings VALUES('x')")

    def test_rejects_update(self):
        with pytest.raises(SQLGuardError):
            _validate_sql("UPDATE bookings SET status='cancelled'")

    def test_rejects_delete(self):
        with pytest.raises(SQLGuardError):
            _validate_sql("DELETE FROM bookings")

    def test_rejects_drop(self):
        with pytest.raises(SQLGuardError):
            _validate_sql("DROP TABLE bookings")

    def test_rejects_truncate(self):
        with pytest.raises(SQLGuardError):
            _validate_sql("TRUNCATE bookings")

    def test_rejects_multi_statement(self):
        with pytest.raises(SQLGuardError, match="Multi-statement"):
            _validate_sql("SELECT 1; SELECT 2")

    def test_rejects_information_schema(self):
        with pytest.raises(SQLGuardError):
            _validate_sql("SELECT * FROM information_schema.tables")

    def test_rejects_pg_prefix(self):
        with pytest.raises(SQLGuardError):
            _validate_sql("SELECT * FROM pg_tables")

    def test_rejects_unknown_table(self):
        with pytest.raises(SQLGuardError, match="not in allowed schema"):
            _validate_sql("SELECT * FROM users")

    def test_rejects_union_injection(self):
        with pytest.raises(SQLGuardError):
            _validate_sql("SELECT * FROM bookings UNION SELECT * FROM properties")

    def test_strips_trailing_semicolon(self):
        # Trailing semicolon should be stripped, not flagged as multi-statement
        result = _validate_sql("SELECT * FROM bookings;")
        assert not result.endswith(";")

    def test_join_allowed(self):
        # Valid join between allowed tables
        sql = "SELECT b.booking_id, r.room_type FROM bookings b JOIN rooms r ON b.room_type = r.room_type"
        result = _validate_sql(sql)
        assert result is not None


# ── RAG question type heuristic ───────────────────────────────────────────────

class TestProductQuestionHeuristic:
    def test_rate_management_is_product(self):
        assert is_product_question("How do I manage room rates?") is True

    def test_review_response_is_product(self):
        assert is_product_question("How to respond to OTA reviews?") is True

    def test_booking_count_is_data(self):
        assert is_product_question("How many bookings confirmed hain?") is False

    def test_revenue_is_data(self):
        assert is_product_question("Total revenue this month?") is False

    def test_occupancy_is_data(self):
        assert is_product_question("What is our occupancy rate?") is False

    def test_onboarding_is_product(self):
        assert is_product_question("Onboarding process kya hai?") is True
