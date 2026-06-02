"""
Unit Tests — No network, no DB required.
Run standalone: pytest tests/test_units.py -v

Tests the Python logic layers in isolation:
  - classify._rule_classify()  — Stage-1 keyword classifier
  - nl_sql._validate_sql()     — SQL guard
  - rag.is_product_question()  — RAG vs SQL routing heuristic
"""
import sys
import os
import pytest

# Allow importing backend modules directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.classify import _rule_classify
from app.nl_sql import _validate_sql, SQLGuardError
from app.rag import is_product_question


# ── Rule-based classifier ─────────────────────────────────────────────────────

class TestRuleClassifier:

    # English
    def test_booking_en(self):
        intent, conf = _rule_classify("do you have a room for tomorrow night for 2 people")
        assert intent == "booking"
        assert conf > 0.5

    def test_booking_hinglish(self):
        intent, conf = _rule_classify("kya kal ka room milega 2 logo ke liye")
        assert intent == "booking"

    def test_cancellation_en(self):
        intent, conf = _rule_classify("please cancel my booking for tonight")
        assert intent == "cancellation"

    def test_cancellation_hinglish(self):
        intent, conf = _rule_classify("cancel kar do meri booking")
        assert intent == "cancellation"

    def test_faq_checkout(self):
        intent, conf = _rule_classify("what time is checkout?")
        assert intent == "faq"

    def test_faq_wifi(self):
        intent, conf = _rule_classify("wifi password kya hai")
        assert intent == "faq"

    def test_faq_rent(self):
        intent, conf = _rule_classify("what is the monthly rent and deposit")
        assert intent == "faq"

    def test_complaint_en(self):
        intent, conf = _rule_classify("the AC in room 203 is not working at all")
        assert intent == "complaint"

    def test_complaint_hinglish(self):
        intent, conf = _rule_classify("AC kaam nahi kar raha")
        assert intent == "complaint"

    def test_complaint_food(self):
        intent, conf = _rule_classify("the food yesterday was cold and bad")
        assert intent == "complaint"

    def test_wakeup_en(self):
        intent, conf = _rule_classify("please give me a wake up call at 6am")
        assert intent == "wakeup"

    def test_wakeup_530(self):
        intent, conf = _rule_classify("wake me up at 5:30 tomorrow please")
        assert intent == "wakeup"

    def test_wakeup_hinglish(self):
        intent, conf = _rule_classify("kal subah 6 baje jagana")
        assert intent == "wakeup"

    def test_empty_returns_none(self):
        intent, conf = _rule_classify("")
        assert intent is None
        assert conf == 0.0

    def test_gibberish_low_confidence(self):
        intent, conf = _rule_classify("xkcd zxqy ??? ##$$")
        assert intent is None or conf < 0.5

    # m14 — ambiguous: rules must NOT give high-confidence cancellation
    def test_m14_ambiguous_low_confidence(self):
        intent, conf = _rule_classify("umm maybe cancel or change, not sure yet")
        # Either not cancellation, or confidence is low enough to trigger confirmation
        if intent == "cancellation":
            assert conf < 0.75, (
                f"m14 ambiguous got high-confidence cancellation: conf={conf}"
            )


# ── SQL Guard ─────────────────────────────────────────────────────────────────

class TestSQLGuard:

    def test_valid_select(self):
        sql = "SELECT COUNT(*) FROM bookings WHERE status = 'confirmed'"
        result = _validate_sql(sql)
        assert "SELECT" in result.upper()

    def test_strips_trailing_semicolon(self):
        result = _validate_sql("SELECT * FROM bookings;")
        assert not result.endswith(";")

    def test_valid_join(self):
        sql = "SELECT b.booking_id, r.room_type FROM bookings b JOIN rooms r ON b.room_type = r.room_type"
        result = _validate_sql(sql)
        assert result is not None

    def test_valid_aggregate(self):
        sql = "SELECT room_type, SUM(amount_inr) FROM bookings GROUP BY room_type"
        result = _validate_sql(sql)
        assert result is not None

    # Write operations
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

    def test_rejects_alter(self):
        with pytest.raises(SQLGuardError):
            _validate_sql("ALTER TABLE bookings ADD COLUMN x TEXT")

    # Injection patterns
    def test_rejects_multi_statement(self):
        with pytest.raises(SQLGuardError, match="Multi-statement"):
            _validate_sql("SELECT 1; SELECT 2")

    def test_rejects_information_schema(self):
        with pytest.raises(SQLGuardError):
            _validate_sql("SELECT * FROM information_schema.tables")

    def test_rejects_pg_prefix(self):
        with pytest.raises(SQLGuardError):
            _validate_sql("SELECT * FROM pg_tables")

    def test_rejects_union(self):
        with pytest.raises(SQLGuardError):
            _validate_sql("SELECT * FROM bookings UNION SELECT * FROM properties")

    def test_rejects_comment_injection(self):
        with pytest.raises(SQLGuardError):
            _validate_sql("SELECT * FROM bookings -- WHERE property_id='hotel_b'")

    # Unknown table
    def test_rejects_unknown_table(self):
        with pytest.raises(SQLGuardError, match="not in allowed schema"):
            _validate_sql("SELECT * FROM users")

    def test_rejects_unknown_table_2(self):
        with pytest.raises(SQLGuardError):
            _validate_sql("SELECT * FROM secret_table")


# ── RAG routing heuristic ─────────────────────────────────────────────────────

class TestProductQuestionHeuristic:

    # Should route to RAG (product/how-to)
    def test_rate_change_is_product(self):
        assert is_product_question("how do I change my room rate for a date?") is True

    def test_review_respond_is_product(self):
        assert is_product_question("how do I respond to an OTA review?") is True

    def test_onboarding_is_product(self):
        assert is_product_question("onboarding kaise hoti hai?") is True

    def test_rate_hinglish_is_product(self):
        assert is_product_question("rate management kaise karte hain?") is True

    # Should route to NL→SQL (data)
    def test_booking_count_is_data(self):
        assert is_product_question("is mahine kitni booking aayi?") is False

    def test_revenue_mmt_is_data(self):
        assert is_product_question("how much revenue did we make from MMT this month?") is False

    def test_noshow_is_data(self):
        assert is_product_question("kitni bookings no-show hui?") is False

    def test_room_type_revenue_is_data(self):
        assert is_product_question("which room type earns the most?") is False

    def test_occupancy_is_data(self):
        assert is_product_question("weekend ka occupancy kya tha?") is False
