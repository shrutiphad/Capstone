"""
2-stage intent classifier:
  Stage 1 — rule-based keyword matching (fast, no LLM call)
  Stage 2 — LLM fallback (Anthropic Claude) when rules give low confidence

Returns (intent, confidence) where intent ∈ {booking, cancellation, faq, complaint, wakeup}
and confidence ∈ [0, 1].

Latency is tracked for P95 reporting.
"""
import time
import json
import logging
import re
import statistics
from typing import Optional
from groq import Groq  

import asyncio

from .config import get_settings

logger = logging.getLogger(__name__)

INTENTS = ["booking", "cancellation", "faq", "complaint", "wakeup"]

# Rule-based keyword signals
RULES: dict[str, list[str]] = {
    "booking": [
        "book", "room", "available", "availability", "stay", "check in", "check-in",
        "checkin", "milega", "chahiye", "kal ka", "tonight", "room hai",
        "vacancy", "accommodation", "reservation", "reserve", "want a room",
        "need a room", "2 logo", "single room", "double room", "suite",
        "deluxe", "standard room", "any room", "is there a room",
    ],
    "cancellation": [
        "cancel kar", "cancel karo", "cancel karna", "band kar",
        "cancellation", "booking cancel", "cancel my booking",
        "cancel the booking", "cancel karna hai",
        # bare "cancel" is intentionally NOT here — it alone in a hedged sentence
        # (m14: "maybe cancel or change") must not auto-fire high-confidence cancellation.
        # The LLM stage handles bare "cancel" with proper confidence calibration.
    ],
    "faq": [
        "checkout time", "check out time", "what time", "wifi", "wi-fi",
        "password", "parking", "breakfast", "restaurant", "pool", "gym",
        "amenities", "facilities", "pet", "smoking", "rent", "deposit",
        "meals", "kya hai", "kya hoga", "kitna", "kab tak",
        "timings", "hours", "what is", "how much", "how do",
    ],
  "complaint": [
    "not working", "broken", "problem", "issue", "complaint",
    "dirty", "noise", "noisy", "smell", "bug", "cockroach",
    "leaking", "leak", "doesn't work", "no hot water", "no water",
    "ac not", "heater not", "light not", "tv not", "unhappy", "terrible",
    "worst", "unacceptable", "disgusting",
    "food was cold", "food was bad", "cold and bad", "bad and cold",
    "yesterday was cold", "cold food", "stale food", "bad food",
    "khaana kharab", "khana thanda", "khaana thanda",
    "kaam nahi kar raha", "kaam nahi", "nahi chal raha",   
],
    "wakeup": [
        "wake up", "wake-up", "wakeup", "wake me", "alarm", "morning call",
        "wake up call", "jagao", "jagana", "uthaana", "uthao", "utha dena",
        "6am", "6 am", "7am", "5am", "5:30", "6:30",
    ],
}

# Greeting words → faq (stage 1 fallback so "hi", "hello", "namaste" don't go to LLM)
GREETINGS = {"hi", "hello", "hey", "namaste", "hii", "helo", "good morning", "good evening"}

# Hedge words that lower confidence on any rule match (especially cancellation)
HEDGE_WORDS = [
    "maybe", "not sure", "or change", "perhaps", "might", "possibly",
    "thinking about", "sochna", "pata nahi", "confirm nahi", "decide nahi",
    "umm", "hmm", "not confirmed",
]

# Latency tracking for P95
_latencies_ms: list[float] = []
_MAX_SAMPLES = 500


def _record_latency(ms: float) -> None:
    _latencies_ms.append(ms)
    if len(_latencies_ms) > _MAX_SAMPLES:
        _latencies_ms.pop(0)


def get_classify_p95() -> float:
    if len(_latencies_ms) < 2:
        return 0.0
    return statistics.quantiles(_latencies_ms, n=20)[18]  # 95th percentile


def _rule_classify(text: str) -> tuple[Optional[str], float]:
    """Stage 1: keyword rules. Returns (intent|None, confidence)."""
    text_lower = text.lower().strip()

    # Greeting shortcut → faq (avoids sending "hi" to LLM)
    if text_lower in GREETINGS or any(text_lower == g for g in GREETINGS):
        return "faq", 0.65

    # Check for hedge words — they reduce confidence ceiling
    has_hedge = any(hw in text_lower for hw in HEDGE_WORDS)

    scores: dict[str, float] = {}
    for intent, keywords in RULES.items():
        hits = sum(1 for kw in keywords if kw in text_lower)
        if hits > 0:
            scores[intent] = hits / len(keywords)

    if not scores:
        return None, 0.0

    best = max(scores, key=scores.get)  # type: ignore[arg-type]

    # Tie-breaking: if complaint and booking are tied (both have 1 hit),
    # and complaint has a specific problem keyword, complaint wins.
    # Prevents "room 203 not working" being classified as booking.
    
    
    # NEW — complaint wins if it has ANY specific problem keyword,
# even if booking scored higher due to list-length artifact
    COMPLAINT_PRIORITY_KEYWORDS = [
        "not working", "broken", "doesn't work", "no hot water", "no water",
        "ac not", "heater not", "light not", "tv not", "leaking", "leak",
        "kaam nahi kar raha", "kaam nahi", "nahi chal raha",
        "dirty", "noise", "noisy", "smell", "bug", "cockroach",
        "food was cold", "food was bad", "cold food", "stale food", "bad food",
        "khaana kharab", "khana thanda", "khaana thanda",
    ]

    if best == "booking" and "complaint" in scores:
        if any(kw in text_lower for kw in COMPLAINT_PRIORITY_KEYWORDS):
            best = "complaint"
            
    # if (
    #     best == "booking"
    #     and "complaint" in scores
    #     and abs(scores["booking"] - scores["complaint"]) < 0.01
    # ):
    #     best = "complaint"

    raw = scores[best]

    # Scale: 1 keyword hit → ~0.65, 2 hits → ~0.80, 3+ → ~0.90+
    confidence = min(0.50 + raw * 15, 0.95)

    # Hedge words cap confidence — forces LLM stage to re-evaluate
    # This is the key guard for m14: "umm maybe cancel or change, not sure yet"
    if has_hedge:
        confidence = min(confidence, 0.55)

    return best, confidence


async def _llm_classify(text: str, property_config: dict) -> tuple[str, float]:
    """Stage 2: LLM classification using Groq."""
    settings = get_settings()

    property_context = ""
    if property_config.get("custom_faqs"):
        faqs = [f['q'] for f in property_config["custom_faqs"][:5]]
        property_context = f"\nProperty FAQ topics: {', '.join(faqs)}"

    prompt = f"""You are classifying hotel guest messages for intent.
Intents: booking | cancellation | faq | complaint | wakeup
Messages can be in English, Hindi, or Hinglish (Hindi-English mix).{property_context}

Message: "{text}"

Respond ONLY with valid JSON: {{"intent": "<one of the 5 intents>", "confidence": <0.0-1.0>}}
If ambiguous, pick the most likely intent but lower the confidence below 0.6.
"""

    try:
        client = Groq(api_key=settings.GROQ_API_KEY)
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                max_tokens=80,
                messages=[{"role": "user", "content": prompt}],
            )
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"```json|```", "", raw).strip()
        data = json.loads(raw)
        intent = data.get("intent", "faq")
        confidence = float(data.get("confidence", 0.5))
        if intent not in INTENTS:
            intent = "faq"
        return intent, min(max(confidence, 0.0), 1.0)
    except Exception as exc:
        logger.warning("LLM classify failed: %s", exc)
        return "faq", 0.4


async def classify(
    text: str, property_config: dict | None = None
) -> tuple[str, float]:
    """
    Full 2-stage classification.
    Returns (intent, confidence).
    Confidence < THRESHOLD → caller should trigger human handoff.
    """
    t0 = time.perf_counter()
    cfg = property_config or {}
    settings = get_settings()

    # Stage 1
    intent, confidence = _rule_classify(text)

    # Stage 2 — LLM if rules didn't fire or gave low confidence
    if intent is None or confidence < settings.CONFIDENCE_THRESHOLD:
        intent_llm, confidence_llm = await _llm_classify(text, cfg)
        # Use LLM result if it's more confident, else keep rule result
        if intent is None or confidence_llm > confidence:
            intent, confidence = intent_llm, confidence_llm

    elapsed = (time.perf_counter() - t0) * 1000
    _record_latency(elapsed)
    logger.info("classify text=%r intent=%s conf=%.2f ms=%.0f", text[:60], intent, confidence, elapsed)
    return intent, confidence
