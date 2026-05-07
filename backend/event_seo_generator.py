"""
Event SEO content generator — calls Azure OpenAI to produce SEO-optimized
content for event hub pages (one URL covering all child markets in a
Polymarket event, e.g. "Bayern vs PSG" → home/draw/away markets).

Mirrors seo_generator.py but takes event-level inputs: title, description,
child market titles, top alert headlines across the whole event. The Gamma
event description is often boilerplate so the prompt nudges the model to
lean on the differentiated alert content for the summary and FAQs.
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
    "Given a Polymarket EVENT (a hub covering multiple related child markets — e.g. a single "
    "sports game with home/draw/away markets, or an election with one market per candidate), "
    "generate SEO-optimized content for the event's hub page.\n\n"

    "## Guidelines\n"
    "- Write for humans searching Google for prediction-market odds on the event.\n"
    "- Target queries like '[event] odds', '[event] prediction market', '[event] Polymarket'.\n"
    "- The page covers ALL child markets in the event, not a single market — phrase the summary "
    "around the event as a whole and mention the range of outcomes being traded.\n"
    "- The Gamma event description is often boilerplate; lean on the alert headlines (the "
    "differentiated PolySpotter content) when writing the summary and FAQs.\n"
    "- FAQs should be questions a searcher would actually ask: about odds, who's betting, "
    "what the smart money is doing, when it resolves.\n"
    "- The SEO title should mention the event and 'odds' or 'prediction market' (under 60 chars).\n"
    "- The meta description should be click-worthy and under 155 characters.\n"
    "- Avoid keyword stuffing; write naturally.\n\n"

    "## Output format\n"
    "Return JSON with these fields:\n"
    "- seo_title (string): keyword-optimized page title, under 60 chars\n"
    "- seo_description (string): click-optimized meta description, under 155 chars\n"
    "- seo_summary (string): 2-3 sentence plain-language event explainer\n"
    "- seo_faqs (array of objects with 'question' and 'answer' keys): 3-5 FAQ pairs\n"
)

RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "event_seo_content",
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
                    "description": "2-3 sentence plain-language event explainer.",
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
                    "description": "3-5 FAQ pairs about this event.",
                },
            },
            "required": ["seo_title", "seo_description", "seo_summary", "seo_faqs"],
            "additionalProperties": False,
        },
    },
}


def _build_event_prompt(
    event_title: str,
    description: str | None = None,
    tags: list[str] | None = None,
    end_date: str | None = None,
    market_titles: list[str] | None = None,
    total_usd: float = 0,
    alert_count: int = 0,
    alert_headlines: list[str] | None = None,
) -> str:
    """Build a user prompt with event context for SEO generation."""
    parts = [f"Event: {event_title}"]
    if description:
        desc = description[:500] + "..." if len(description) > 500 else description
        parts.append(f"Description: {desc}")
    if tags:
        parts.append(f"Categories: {', '.join(tags)}")
    if end_date:
        parts.append(f"Resolves by: {end_date}")
    if market_titles:
        parts.append(f"Child markets in this event ({len(market_titles)}):")
        for t in market_titles[:10]:
            parts.append(f"  - {t}")
    if total_usd > 0:
        parts.append(f"Total smart money tracked across event: ${total_usd:,.0f}")
    if alert_count > 0:
        parts.append(f"Number of smart money signals across event: {alert_count}")
    if alert_headlines:
        parts.append("Recent alert headlines (use for FAQs and summary flavor):")
        for h in alert_headlines[:5]:
            parts.append(f"  - {h}")
    return "\n".join(parts)


def generate_event_seo_content(
    event_title: str,
    description: str | None = None,
    tags: list[str] | None = None,
    end_date: str | None = None,
    market_titles: list[str] | None = None,
    total_usd: float = 0,
    alert_count: int = 0,
    alert_headlines: list[str] | None = None,
) -> dict | None:
    """Generate SEO content for an event hub page via Azure OpenAI.

    Returns dict with seo_title, seo_description, seo_summary, seo_faqs,
    or None if generation fails or API key is missing.
    """
    if not AZURE_OPENAI_API_KEY:
        return None

    client = OpenAI(base_url=AZURE_OPENAI_ENDPOINT, api_key=AZURE_OPENAI_API_KEY)
    user_prompt = _build_event_prompt(
        event_title, description, tags, end_date,
        market_titles, total_usd, alert_count, alert_headlines,
    )

    try:
        response = client.chat.completions.create(
            model=MODEL,
            max_completion_tokens=2000,
            messages=[
                {"role": "developer", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format=RESPONSE_SCHEMA,
        )
        text = response.choices[0].message.content
        result = json.loads(text)
        return {
            "seo_title": result.get("seo_title", ""),
            "seo_description": result.get("seo_description", ""),
            "seo_summary": result.get("seo_summary", ""),
            "seo_faqs": result.get("seo_faqs", []),
        }
    except Exception as e:
        print(f"[event_seo_generator] ERROR generating SEO content: {e}")
        return None
