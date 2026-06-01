"""
RAG over the kb/ directory.
Uses simple TF-IDF-style scoring to find relevant KB articles,
then Claude to generate a grounded answer with a source citation.
"""
import logging
import os
import re
from pathlib import Path

import anthropic

from .config import get_settings

logger = logging.getLogger(__name__)

# ── KB loading ────────────────────────────────────────────────────────────────

_KB_CACHE: dict[str, str] = {}

def _load_kb(kb_dir: str | None = None) -> dict[str, str]:
    global _KB_CACHE
    if _KB_CACHE:
        return _KB_CACHE

    if kb_dir is None:
        # Walk up from this file to find kb/
        base = Path(__file__).parent.parent
        kb_dir = str(base / "kb")

    kb: dict[str, str] = {}
    kb_path = Path(kb_dir)
    if kb_path.exists():
        for f in kb_path.glob("*.md"):
            kb[f.name] = f.read_text(encoding="utf-8")
    else:
        logger.warning("KB directory not found: %s", kb_dir)

    _KB_CACHE = kb
    logger.info("Loaded %d KB files: %s", len(kb), list(kb.keys()))
    return kb


# ── Relevance scoring ─────────────────────────────────────────────────────────

PRODUCT_KEYWORDS = {
    "rate", "rates", "price", "pricing", "room rate", "channel manager",
    "review", "reviews", "ota review", "respond", "response",
    "onboard", "onboarding", "setup", "configure", "connect",
    "how do", "how to", "kaise", "kya hota", "explain",
}

def _is_product_question(question: str) -> bool:
    q_lower = question.lower()
    return any(kw in q_lower for kw in PRODUCT_KEYWORDS)


def _score_kb(question: str, kb: dict[str, str]) -> list[tuple[str, float, str]]:
    """Simple term overlap scoring. Returns [(filename, score, content)]."""
    q_terms = set(re.findall(r"\w+", question.lower()))
    results = []
    for fname, content in kb.items():
        c_terms = set(re.findall(r"\w+", content.lower()))
        overlap = len(q_terms & c_terms)
        score = overlap / max(len(q_terms), 1)
        results.append((fname, score, content))
    results.sort(key=lambda x: x[1], reverse=True)
    return results


# ── Main RAG function ─────────────────────────────────────────────────────────

async def rag_answer(question: str) -> dict:
    """
    Returns {answer, source, type}.
    If no relevant KB article found → answer=None, type='refused'.
    """
    kb = _load_kb()
    if not kb:
        return {
            "answer": "Knowledge base is not available.",
            "source": None,
            "type": "refused",
        }

    ranked = _score_kb(question, kb)
    best_file, best_score, best_content = ranked[0]

    # If no article is even remotely relevant, refuse
    if best_score < 0.05:
        return {
            "answer": "Mujhe is sawal ka jawab mere knowledge base mein nahi mila. Koi aur pooch sakte hain?",
            "source": None,
            "type": "refused",
        }

    # Use top-2 articles if both are relevant
    context_parts = [(best_file, best_content)]
    if len(ranked) > 1 and ranked[1][1] >= 0.03:
        context_parts.append((ranked[1][0], ranked[1][2]))

    context = "\n\n".join(f"[{fname}]\n{content}" for fname, content in context_parts)

    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    prompt = f"""You are a helpful hotel operations assistant. Answer the question using ONLY the provided knowledge base content.
If the answer is not in the knowledge base, say so clearly — do NOT fabricate.

Knowledge Base:
{context}

Question: "{question}"

Instructions:
- Answer in 1-3 sentences
- Cite the source file name at the end, e.g. [Source: rates.md]
- If question is in Hindi/Hinglish, answer in Hinglish
- If the KB does not contain the answer, reply: "Yeh information mere knowledge base mein nahi hai."
"""

    try:
        response = await client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        answer_text = response.content[0].text.strip()

        # Extract cited source from answer or use best match
        cited = best_file
        cite_match = re.search(r"\[Source:\s*([\w.]+)\]", answer_text)
        if cite_match:
            cited = cite_match.group(1)

        return {
            "answer": answer_text,
            "source": cited,
            "type": "rag",
        }
    except Exception as exc:
        logger.error("RAG LLM failed: %s", exc)
        return {
            "answer": "Technical error — please try again.",
            "source": None,
            "type": "error",
        }


def is_product_question(question: str) -> bool:
    """Heuristic: is this a product-help question (→ RAG) or a data question (→ SQL)?"""
    data_keywords = {
        "booking", "bookings", "revenue", "kitni booking", "occupancy",
        "how many", "kitna", "total", "count", "sum", "average", "which month",
        "no_show", "no show", "cancelled", "confirmed", "source", "mmt",
        "booking_com", "agoda", "room type", "earn", "earnings", "income",
        "kharcha", "kamai", "weekend", "weekly", "monthly", "mahine mein",
    }
    q_lower = question.lower()

    # If it has explicit data query patterns, it's a SQL question
    if any(kw in q_lower for kw in data_keywords):
        return False

    # If it has product/how-to patterns, it's a RAG question
    return _is_product_question(question)
