"""
Hourly Twitter bot for PolySpotter.

Runs as a standalone script (Railway cron, once per hour at :00):
    python backend/twitter_bot.py

Flow: fetch last-hour alerts → dedup → send top 5 to GPT-5.4 → either post
a tweet via the X API or skip → record to tweeted_alerts.

Design spec: docs/superpowers/specs/2026-04-19-twitter-bot-design.md
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

import psycopg2
import requests
import tweepy
from dotenv import load_dotenv
from openai import OpenAI
from psycopg2.extras import RealDictCursor


load_dotenv()

# --- Config (from env) --------------------------------------------------------

POLYSPOTTER_API_URL = os.environ.get("POLYSPOTTER_API_URL", "https://api.polyspotter.com")
TWITTER_BOT_MIN_SCORE = float(os.environ.get("TWITTER_BOT_MIN_SCORE", "5.0"))
TWITTER_BOT_DRY_RUN = os.environ.get("TWITTER_BOT_DRY_RUN", "false").lower() == "true"

X_CONSUMER_KEY = os.environ.get("X_CONSUMER_KEY", "")
X_CONSUMER_KEY_SECRET = os.environ.get("X_CONSUMER_KEY_SECRET", "")
X_ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN", "")
X_ACCESS_TOKEN_SECRET = os.environ.get("X_ACCESS_TOKEN_SECRET", "")

AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT = "https://gpt-5-mati-labs.cognitiveservices.azure.com/openai/v1/"
MODEL = "gpt-5.4"

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Time window for candidate alerts (slack beyond exactly 60 minutes to tolerate
# cron drift).
LOOKBACK_MINUTES = 65

# Soft-dedup window: don't tweet same (wallet, condition_id) within this many hours.
SOFT_DEDUP_HOURS = 24

# Hard length cap for tweets (under X's 280 limit, leaves safety margin).
TWEET_MAX_CHARS = 260


# --- Logging ------------------------------------------------------------------

def log_event(event: str, **fields: Any) -> None:
    """Emit a single-line JSON log event to stdout."""
    payload = {"event": event, **fields}
    # Ensure values are JSON-safe.
    print(json.dumps(payload, default=str), flush=True)


if __name__ == "__main__":
    sys.exit(0)  # placeholder; real main() added in Task 10
