"""
SEO content generator — calls Azure OpenAI to produce SEO-optimized content
for market pages (title, description, summary, FAQs) in a single API call.

Follows the same Azure OpenAI pattern as llm_filter.py.
"""

from __future__ import annotations

import json
import os

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
MODEL = os.environ.get("AZURE_OPENAI_MODEL", "")

SYSTEM_PROMPT = (
    "You are an SEO content specialist for PolySpotter, a Polymarket smart money tracker. "
    "Given a prediction market's metadata, generate SEO-optimized content for the market's page.\n\n"

    "## Guidelines\n"
    "- Write for humans searching Google for prediction market odds, outcomes, and analysis.\n"
    "- Target search queries like '[topic] prediction market odds', '[topic] Polymarket', "
    "'will [outcome] happen prediction market'.\n"
    "- Use natural language, not keyword stuffing.\n"
    "- FAQs should be genuine questions a searcher would ask about this specific market.\n"
    "- Keep the summary informative and factual — mention current odds, what the market covers, "
    "and when it resolves.\n"
    "- The SEO title should be keyword-rich but readable (under 60 chars ideal).\n"
    "- The meta description should be click-worthy and under 155 characters.\n\n"

    "## Output format\n"
    "Return JSON with these fields:\n"
    "- seo_title (string): keyword-optimized page title, under 60 chars\n"
    "- seo_description (string): click-optimized meta description, under 155 chars\n"
    "- seo_summary (string): 2-3 sentence plain-language market explainer\n"
    "- seo_faqs (array of objects with 'question' and 'answer' keys): 3-5 FAQ pairs\n"
)

RESPONSE_FORMAT = {
    "type": "json_schema",
    "name": "seo_content",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "seo_title": {
                "type": "string",
                "description": "Keyword-optimized page title, under 60 chars.",
            },
            "seo_description": {
                "type": "string",
                "description": "Click-optimized meta description, under 155 chars.",
            },
            "seo_summary": {
                "type": "string",
                "description": "2-3 sentence plain-language market explainer.",
            },
            "seo_faqs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "answer": {"type": "string"},
                    },
                    "required": ["question", "answer"],
                    "additionalProperties": False,
                },
                "description": "3-5 FAQ pairs about this market.",
            },
        },
        "required": ["seo_title", "seo_description", "seo_summary", "seo_faqs"],
        "additionalProperties": False,
    },
}


def _build_market_prompt(
    market_title: str,
    description: str | None = None,
    tags: list[str] | None = None,
    end_date: str | None = None,
    total_usd: float = 0,
    alert_count: int = 0,
    alert_headlines: list[str] | None = None,
) -> str:
    """Build a user prompt with market context for SEO generation."""
    parts = [f"Market: {market_title}"]
    if description:
        desc = description[:500] + "..." if len(description) > 500 else description
        parts.append(f"Description: {desc}")
    if tags:
        parts.append(f"Category: {', '.join(tags)}")
    if end_date:
        parts.append(f"Resolution date: {end_date}")
    if total_usd > 0:
        parts.append(f"Total smart money tracked: ${total_usd:,.0f}")
    if alert_count > 0:
        parts.append(f"Number of smart money signals: {alert_count}")
    if alert_headlines:
        parts.append("Recent alert headlines:")
        for h in alert_headlines[:5]:
            parts.append(f"  - {h}")
    return "\n".join(parts)


def generate_seo_content(
    market_title: str,
    description: str | None = None,
    tags: list[str] | None = None,
    end_date: str | None = None,
    total_usd: float = 0,
    alert_count: int = 0,
    alert_headlines: list[str] | None = None,
) -> dict | None:
    """Generate SEO content for a market page via Azure OpenAI.

    Returns dict with seo_title, seo_description, seo_summary, seo_faqs,
    or None if generation fails or API key is missing.
    """
    if not AZURE_OPENAI_API_KEY:
        return None

    client = OpenAI(base_url=AZURE_OPENAI_ENDPOINT, api_key=AZURE_OPENAI_API_KEY)
    user_prompt = _build_market_prompt(
        market_title, description, tags, end_date,
        total_usd, alert_count, alert_headlines,
    )

    try:
        response = client.responses.create(
            model=MODEL,
            max_output_tokens=2000,
            instructions=SYSTEM_PROMPT,
            input=user_prompt,
            text={"format": RESPONSE_FORMAT},
        )
        text = response.output_text
        result = json.loads(text)
        return {
            "seo_title": result.get("seo_title", ""),
            "seo_description": result.get("seo_description", ""),
            "seo_summary": result.get("seo_summary", ""),
            "seo_faqs": result.get("seo_faqs", []),
        }
    except Exception as e:
        print(f"[seo_generator] ERROR generating SEO content: {e}")
        return None
