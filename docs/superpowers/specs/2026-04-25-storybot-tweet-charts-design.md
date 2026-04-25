# Storybot — Auto-Generated Charts on Twitter Simple Bot

**Date:** 2026-04-25
**Status:** Approved, pending implementation plan
**Affects:** [storybot/twitter_simple.py](../../../storybot/twitter_simple.py), new module `storybot/charts.py`

## Goal

Attach an auto-generated chart image to every tweet posted by the simple bot when the alert supports it. Currently the bot posts text-only tweets at [twitter_simple.py:296](../../../storybot/twitter_simple.py#L296) (`twitter_client.create_tweet(text=text)`), and link unfurls are explicitly disabled — the polyspotter.com URL is stripped before posting at [twitter_simple.py:55-57](../../../storybot/twitter_simple.py#L55-L57). That leaves the tweet as a text-only object in a feed that algorithmically rewards media. From a 0-follower start, the single largest reach lever available without scope creep is a media attachment per tweet.

The chart is not a brand decoration — each chart type is chosen to *prove the surprise* the tweet leads with. A tweet about a 906× volume spike should show the spike; a tweet about a 178-20 wallet should show the record; a tweet about a single buy that flipped a market should show the price line.

## Non-goals

- No changes to storybot.py (the long-form thread bot), to the seeder, to detection strategies, or to the backend API.
- No new chart-rendering route in the Next.js frontend. The existing OG route at `frontend/src/app/api/og/[alertId]/route.jsx` is left alone.
- No new database tables or migrations. The `price_candles` Postgres table is not depended on; live CLOB API is the source for time-series.
- No reply-chain attachments (link in a self-reply). The bot stays single-tweet; chart goes inline as media.
- No chart caching or persistence. Each run renders fresh.
- No multi-image tweets. One image per tweet, max.

## Architecture

### New module: `storybot/charts.py`

Single module exporting:

- **One render function per chart type**, each returning `bytes` (PNG):
  - `render_wallet_record_card(data: WalletRecordCardData) -> bytes`
  - `render_price_sparkline(data: PriceSparklineData) -> bytes`
  - `render_volume_bar(data: VolumeBarData) -> bytes`
  - `render_cluster_card(data: ClusterCardData) -> bytes`
- **Per-chart data fetchers**, each returning the typed dict above or `None` if data is unavailable:
  - `fetch_wallet_record_card_data(alert: dict) -> WalletRecordCardData | None`
  - `fetch_price_sparkline_data(alert: dict) -> PriceSparklineData | None`
  - `fetch_volume_bar_data(alert: dict) -> VolumeBarData | None`
  - `fetch_cluster_card_data(alert: dict) -> ClusterCardData | None`
- **House-style constants** (one source of truth):
  - Canvas: 1200×675 (16:9, fits Twitter's 1.91:1 in-feed preview without crop).
  - Background: `#0E1117`. Primary text: `#FFFFFF`. Accent: brand green `#22C55E` (wins / size-up). Loss/red: `#EF4444`. Muted: `#9CA3AF`.
  - Font: matplotlib default (DejaVu Sans). Single weight via size only. No grid lines, no spines except where they carry information, no chartjunk.
- **One dispatcher**: `render_chart_for_alert(chart_type: str, alert: dict) -> bytes | None`. Looks up the fetcher + renderer for the requested type, returns `None` on any failure.

### Changes to `storybot/twitter_simple.py`

**1. Extend `SYSTEM_PROMPT`** at [twitter_simple.py:88](../../../storybot/twitter_simple.py#L88) with chart guidance and a new JSON field. New JSON schema (replaces the current schema block at [twitter_simple.py:221-227](../../../storybot/twitter_simple.py#L221-L227)):

```json
{
  "decision": "post" | "skip",
  "reason": "<one short sentence>",
  "tweet": "<tweet text>" | null,
  "alert_ids": [<int>, ...] | null,
  "chart_type": "price_sparkline" | "volume_bar" | "wallet_record_card" | "cluster_card" | "none"
}
```

A new "Chart selection" section in the prompt explains: *the chart should prove the surprise the tweet's hook leads with*. Pick the chart type that visually carries the lead clause:

- Tweet leads with a price move ("just flipped from 32c to 41c") → `price_sparkline`
- Tweet leads with a volume multiplier ("906× normal volume") → `volume_bar`
- Tweet leads with a wallet record ("a 178-20 account") or wallet age ("a 12-day-old account") → `wallet_record_card`
- Tweet leads with coordinated flow ("five accounts sharing a funder") and no single wallet record dominates → `cluster_card`
- If nothing supports a chart cleanly → `none`

**2. Extend `validate_decision`** at [twitter_simple.py:264](../../../storybot/twitter_simple.py#L264) to validate `chart_type` against the enum. Missing field → treat as `"none"`. Unknown value → validation error.

**3. Add `prepare_chart(decision, seed_alerts) → bytes | None`** as a new module-level function. Responsibilities:

- Resolve the alert by `alert_ids[0]` (the LLM may pass several but the chart is keyed off the lead alert).
- Run the **fallback ladder**:
  1. Try the LLM-requested `chart_type` via `render_chart_for_alert`. If non-None, return.
  2. If that returned `None`, try `wallet_record_card` *only if* a contributing wallet has ≥10 prior bets in `wallet_pnl`.
  3. If that also returned `None`, return `None`.
- Catch every exception (network, render, missing data); never raise. Log the failure with `log("chart_fallback", ...)` so the LLM prompt and the rules can be tuned over time.

**4. Modify `post_tweet`** at [twitter_simple.py:292-301](../../../storybot/twitter_simple.py#L292-L301) to accept an optional `media_png: bytes | None` argument. When present, upload via tweepy v1.1 `API.media_upload(filename="chart.png", file=BytesIO(media_png))` to obtain a `media_id`, then pass `media_ids=[media_id]` to the existing v2 `Client.create_tweet(text=...)`. When absent, behavior is unchanged.

This means `_build_twitter_client` at [storybot.py:1479-1485](../../../storybot/storybot.py#L1479-L1485) needs a sibling that returns a v1.1 `tweepy.API` instance (OAuth1 with the same four creds). Add `_build_twitter_api_v1` adjacent to it, keep the v2 client for posting.

**5. Wire `prepare_chart` into `main`** at [twitter_simple.py:375-380](../../../storybot/twitter_simple.py#L375-L380), between validation and posting. Failures are non-fatal and produce a text-only tweet.

### Data flow

```
fetch_seed_alerts → filter_posted_alerts → write_tweet (LLM picks chart_type)
  → decision{decision, tweet, alert_ids, chart_type, reason}
  → validate_decision
  → prepare_chart(decision, seed_alerts)  ──any failure──▶ png = None
  → post_tweet(tweet, png, twitter_v2_client, twitter_v1_api, dry_run)
  → record_tweet (unchanged)
```

The LLM owns chart selection; `prepare_chart` is the deterministic floor. Selection lives in the LLM because chart choice depends on the angle of the tweet, not just the strategy of the alert (a `wallet_clustering` alert where one wallet has a 178-20 record should chart the record, not the cluster). The fallback ladder lives in `prepare_chart` because the LLM occasionally requests data that isn't there.

## Chart catalog

All charts share the house style above. All are 1200×675 PNGs.

### `wallet_record_card` — universal credibility card

**When chosen:** tweets that lead with a wallet's record or age. Also the deterministic fallback target whenever ≥1 contributing wallet has ≥10 prior bets logged in `wallet_pnl`.

**Data needed:**
- Wallet's record string (W-L), win %, total bet count from `wallet_pnl`.
- Wallet's age in days, if available (from existing wallet metadata used by `new_wallet_large_bet`).
- Market title from the alert.
- Bet size on this market, outcome side from `llm_copy_action`.

**Layout:** market title at top in muted color. Hero number ("88%" or "29-4") centered, large. Subtitle one line below: "across 50+ Polymarket bets" or "record across all prior markets". Horizontal record bar (green wins / red losses, proportional). Footer line: "$80k on Yes — Will Trump win 2024?" with the size and outcome.

**Failure conditions:** wallet has <10 prior bets, or `wallet_pnl` row missing → fetcher returns `None`.

### `price_sparkline` — show the move

**When chosen:** tweets that lead with a price move, a single market-moving buy, or near-resolution timing where the late move IS the story.

**Data needed:**
- Time-series price for the bet's outcome token: CLOB `GET https://clob.polymarket.com/prices-history?market=<token_id>&interval=1h&fidelity=60` for the last 24h. Falls back to `interval=1d&fidelity=60` if 1h returns empty.
- Alert trades: timestamp + price per trade, available in the alert's trades JSON (already fetched by `fetch_seed_alerts`).
- Market title, outcome side.

**Layout:** title at top ("Will Trump win 2024? — Yes" in muted color). Single line plot of price over time, accent color, no gridlines. Trade markers as filled dots on the line, sized roughly by trade $. Y-axis labeled with the start price and end price only ("32c → 41c"); no axis ticks elsewhere. X-axis labeled with the visible time window only ("last 24h").

**Failure conditions:** CLOB returns <2 price points, or all alert trades fall outside the visible window, or price never moves more than 1c → fetcher returns `None`.

### `volume_bar` — the 906× card

**When chosen:** tweets that lead with a volume multiplier or a market that punched above its weight.

**Data needed:**
- Today's volume on the market: sum of `size * price` from Data API `GET https://data-api.polymarket.com/trades?market=<condition_id>&start_time=<24h ago>` (paginated until exhausted).
- 7-day baseline: same endpoint with `start_time=<8 days ago>` and `end_time=<1 day ago>`, divided by 7.
- Market title.

**Layout:** market title at top. Two horizontal bars stacked vertically — top bar labeled "7-day daily average" with the dollar figure, much smaller. Bottom bar labeled "today" with the dollar figure, full width. Hero label between them: "906×". Accent color on the "today" bar.

**Failure conditions:** today's volume < $1k (not actually a story), or 7-day baseline is zero, or the multiplier is <5× → fetcher returns `None`.

### `cluster_card` — coordinated flow

**When chosen:** tweets that lead with multi-wallet coordination and no single wallet record dominates.

**Data needed:**
- Cluster signals from the alert's `signals` JSON (cluster size, total $, side).
- Per-wallet $ size on this market from the alert's trades JSON.
- Shared-funder address from `wallet_funders` (already populated by the clustering strategy).

**Layout:** market title at top. N horizontal bars, one per wallet, each labeled with a pseudonym ("wallet A" / "wallet B" / …) and a $ figure, all in the same accent color since they're all on the same side. Bars sized proportionally to each wallet's contribution. Total below: "$394k on Arsenal". Footer line: "Shared funder: 0xabc…1234" (truncated address).

**Failure conditions:** fewer than 2 contributing wallets, or no shared funder recorded → fetcher returns `None`.

## Operational concerns

### Dry-run

`TWITTER_SIMPLE_DRY_RUN=true` already short-circuits posting at [twitter_simple.py:294-295](../../../storybot/twitter_simple.py#L294-L295). Extend it: when dry-run is set and `prepare_chart` returns bytes, write the PNG to `storybot/dry_runs/twitter_simple_<run_id>.png` so the chart can be eyeballed before going live. Tweet text continues to print to stdout as today at [twitter_simple.py:387](../../../storybot/twitter_simple.py#L387).

### Logging

Three new log events:
- `chart_selected` — `chart_type` from the LLM, `alert_id`, and which fetcher succeeded (LLM-pick vs. fallback vs. none).
- `chart_fallback` — emitted when the LLM-requested chart fell through to fallback (so we can tune the prompt).
- `chart_render_error` — emitted on any caught exception during render (so we can tune the renderers). Never re-raised.

### Tests

- `test/test_charts.py`: per-chart-type unit tests with synthetic fixture data. Each test asserts non-empty bytes, `1200×675` dimensions (parsed via Pillow), and PNG signature. No visual assertions.
- `test/test_charts_dispatcher.py`: dispatcher returns `None` cleanly when fetchers raise, return `None`, or the chart_type is unknown.
- `storybot/render_all_charts.py`: dev-only smoke script that pulls the most recent alert from Postgres, renders all four chart types to `storybot/dry_runs/`, prints the file paths. Not run in CI; used for visual review when changing the house style.
- Existing `validate_decision` tests extend to cover the new `chart_type` field (valid enum / missing / unknown / null).

### Dependencies

Add `matplotlib` and `Pillow` to `requirements.txt` (Pillow is needed by the unit tests to parse PNG dimensions; matplotlib pulls numpy transitively).

### Twitter API tier — verify before implementation

The current bot posts via tweepy v2 `Client.create_tweet`, which is supported on the X Free tier. Media upload is **not** part of the Free tier — it requires a paid plan and access to either v1.1 `media/upload` or v2 `/2/media/upload`. X API pricing and tier capabilities have changed several times; do not encode a specific plan name or price into the design.

This is the one non-code-quality risk in the design. **Before starting implementation, confirm the X account this posts from has media-upload access** — either by attempting a manual upload via the existing creds with a throwaway PNG, or by checking the developer portal for the active plan. If the account does not have media access, charts cannot ship without a plan change and this design must be revisited.

## Risks & open questions

1. **CLOB `prices-history` rate limits.** The bot runs on cron; if cron fires faster than CLOB tolerates, sparklines will sometimes 429. Acceptable: the fallback ladder catches this and the tweet still posts.
2. **Wallet pseudonym source.** Cluster card labels need stable pseudonyms ("wallet A" / "wallet B"). The existing frontend uses `frontend/src/lib/pseudonym.js`; the simple bot should mirror its hashing scheme so the same wallet gets the same pseudonym across runs and across surfaces. Implementation should port the pseudonym function to Python rather than inventing a parallel scheme.
3. **Chart-tuning loop.** The first month of charts will look wrong in subtle ways (font weight, spacing, color choice). Plan to ship `render_all_charts.py` and iterate on the house style after seeing real alerts; do not over-design the first version.
4. **LLM hallucinating chart_type fields.** Mitigated by validation + fallback ladder, but if the LLM frequently picks a type whose data is missing, the fallback log will show it and the prompt needs more explicit guidance on which signals support which charts.

## Implementation order

1. Verify Twitter API tier (out-of-band check).
2. Build `storybot/charts.py` with house style + the simplest chart (`wallet_record_card`) end-to-end, including unit tests.
3. Add `chart_type` to the JSON schema, the prompt, and `validate_decision`. Extend dry-run to write PNGs.
4. Wire `prepare_chart` and the v1.1 client into `post_tweet`. Confirm a real chart posts in dry-run.
5. Add the remaining three chart types one at a time, each with its fetcher + tests + dry-run inspection.
6. Soak in dry-run for a few cron cycles; review the rendered PNGs; tune the house style.
7. Flip to live posting; monitor `chart_fallback` and `chart_render_error` log volume for the first week and tune.
