# Twitter Pipeline — Chart Grid Design

## Background

The twitter_pipeline currently attaches a single chart to each tweet. The
chart_picker stage chooses one of five chart types (`wallet_record_card`,
`fresh_wallet_card`, `price_sparkline`, `volume_bar`, `cluster_card`) plus
a `hook_anchor`, and the writer composes a tweet around that single fact.

Surveying recent live runs (`storybot/live_runs/twitter_pipeline_*.png`):

- The picker chose `wallet_record_card` for every recent run. Tweets are
  starting to look interchangeable.
- Each event has 4–6 facts that matter (sharp record, cluster total, linked
  accounts, time to resolution, price move, volume spike, fresh wallet).
  The chart proves only one of them; the tweet text has to carry the rest
  in plain English, and 280 chars is not enough.
- The chart's existing footer ("$221k on Under — 7 linked accounts") shows
  that the supporting cluster facts deserve visual treatment, but at present
  they're sized as an afterthought.

We want the chart to carry the full setup at a glance and let the tweet do
less work.

## Goal

Replace the single-chart attachment with a hero+tiles grid composed inside
the same 1200×675 canvas. The hero proves the dominant surprising fact
(unchanged role from today's chart_picker output); a strip of three stat
tiles surrounds it with the supporting numeric facts that today's chart
buries or omits.

The chart becomes the story-at-a-glance; the tweet becomes a hook.

## Layout

The Twitter in-feed preview is 1.91:1 — anything taller than 1200×675 gets
cropped, so we keep the canvas. Inside it:

```
┌────────────────────────┬──────────────┐
│                        │              │
│        HERO            │    TILE 1    │
│      (~720 × 675)      │              │
│   the existing chart   ├──────────────┤
│   types, re-targeted   │              │
│   to a narrower frame  │    TILE 2    │
│                        ├──────────────┤
│                        │              │
│                        │    TILE 3    │
└────────────────────────┴──────────────┘
       ~60% × 100%        ~40% × 33% each
```

A 1px MUTED divider between hero and tile column. A 1px MUTED divider
between tile slots. No title bar, no footer band — same minimal house
style as today.

This shape suits every existing hero (each has a vertical title→big
number→accent rhythm) better than a hero-top/tiles-bottom banner, and
720×675 keeps the hero's giant typography readable while 480×225 tile
slots are large enough for a stat tile to dominate.

## Tile inventory

Eight tile types, all driven from `facts_bundle` plus one new field
(`volume_multiplier_x`, computed at stage 2). Each has a "show if"
threshold; failing tiles drop out of the running.

| Tile | Renders as | Show if |
|---|---|---|
| **CLOCK** | "11 MIN · to tip" / "6h · to close" | `minutes_to_resolution` set (under 720 → "min", else hours) |
| **CLUSTER $** | "$220K · cluster flow" | `total_usd >= 25_000` (configurable) AND hero ≠ `cluster_card` |
| **LINKED ACCOUNTS** | "7 wallets · one funder" | `cluster_size >= 3` AND hero ≠ `cluster_card` |
| **VOLUME ×** | "12× · usual volume" | `has_volume_spike == True` AND `volume_multiplier_x` known AND hero ≠ `volume_bar` |
| **PRICE MOVE** | "32¢ → 41¢" | `biggest_price_move` set AND `\|to-from\| >= 0.03` AND hero ≠ `price_sparkline` |
| **SHARP RECORD** | "24-1 · sharp wallet" | `has_sharp_wallet` set AND hero ≠ `wallet_record_card` |
| **FRESH WALLET** | "9-DAY · old account" | `has_fresh_wallet` set AND hero ≠ `fresh_wallet_card` |
| **WALLETS** | "15 accounts · one event" | `distinct_wallets >= 5` (fallback only) |

The "hero ≠ X" dedup rule is universal: any tile whose primary fact is
already the hero's primary fact is suppressed. This prevents the
"hero = wallet_record_card showing 24-1, tile = SHARP RECORD showing
24-1" failure mode for every hero type.

### Selection priority

`select_tiles(hero_type, facts_bundle)` filters the inventory by each
tile's "show if" condition (which already includes the hero-dedup), then
takes the first three from this fixed priority list:

1. **CLOCK** — urgency always wins.
2. **CLUSTER $** — biggest unique-to-this-event number.
3. **VOLUME ×**
4. **PRICE MOVE**
5. **LINKED ACCOUNTS**
6. **SHARP RECORD**
7. **FRESH WALLET**
8. **WALLETS** — filler.

If fewer than 3 tiles pass, render however many we have. If zero pass,
fall back to the single-chart 1200×675 layout (the grid is a
density-display feature; without density, degrade).

## Hero panels

Each existing hero is refactored to fit the 720×675 region and to drop
its now-redundant cluster footer. Two changes per hero:

**1. Re-target the canvas to 720×675.** Most heroes are already
vertically structured and translate cleanly to a narrower frame.
Sparkline and volume_bar will compress on the x-axis; that's fine —
they were never time-detailed, just shape-conveying.

**2. Replace the cluster footer with a personal subtitle** describing
what the hero's specific subject did:

| Hero | Personal subtitle |
|---|---|
| `wallet_record_card` | "$7k · on Under" *(uses existing `bet_size_usd`)* |
| `fresh_wallet_card` | "$80k · on Yes" |
| `price_sparkline` | "Under · dominant outcome" |
| `volume_bar` | "$140k · peak hour" |
| `cluster_card` | (no subtitle — cluster IS the subject; tiles carry it) |

If the data needed for a subtitle is missing, drop the subtitle — don't
print "$? on Under". Each hero was originally designed to read without it.

## Pipeline integration

```
stage 1: event_picker      (unchanged)
stage 2: data_fetcher      (adds volume_multiplier_x to facts_bundle when has_volume_spike)
stage 3: chart_picker      (LLM — picks HERO chart_type + hook_anchor; same JSON shape)
   ↓
NEW: select_tiles(hero, facts_bundle) → list[TileSpec]   (deterministic)
   ↓
stage 4: writer            (payload gains image_tiles list; one-line prompt addition)
   ↓
NEW: compose_chart(hero_type, alert, facts_bundle, tile_specs) → PNG bytes
```

### `chart_grid.py` (new module)

Lives next to `charts.py` to keep the latter from sprawling further past
its current 1220 lines. Owns:

- `select_tiles(hero_type, facts_bundle, condition_id) -> list[TileSpec]` —
  pure function, applies the priority list, dedupes against the hero,
  returns up to 3 specs.
- `_draw_tile(ax, spec)` — paints one stat tile (big number + label) into
  a given Axes.
- `compose_chart(hero_type, alert, facts_bundle, tile_specs, ...) -> bytes` —
  creates a single 1200×675 matplotlib figure, carves it into a hero region
  (720×675) and three tile regions (480×225 each), invokes the hero
  renderer on its region, paints tiles, returns PNG bytes. No PIL
  compositing — single matplotlib figure.

### `charts.py` (refactor)

Each existing `render_X(data) -> bytes` splits into:

- `_draw_X(ax, data)` — internal, takes an Axes, draws the chart.
- `render_X(data) -> bytes` — public, creates a 720×675 fig, calls
  `_draw_X`, returns bytes.

The public single-image renderers stay callable for tests, articlebot,
and `render_all_charts.py`. compose_chart calls `_draw_X` on the hero
region of the shared figure.

### Stage 2: volume multiplier

The VOLUME × tile needs the baseline volume that `volume_bar` already
fetches via `_fetch_baseline_avg_volume(condition_id)`. To avoid double
fetching when the hero IS volume_bar, compute `volume_multiplier_x` once
at stage 2 (one extra Gamma call per cluster, gated by `has_volume_spike`)
and add it to `facts_bundle`. Both the hero renderer and the tile reader
consume from the bundle.

### Stage 4: writer prompt addendum

Add one sentence to `SYSTEM_PROMPT_WRITER`, gated on `image_tiles` being
non-empty in the payload:

> The chart you ship with this tweet is a grid: a hero panel
> (corresponding to chart_type) plus 3 stat tiles drawn from {CLOCK,
> CLUSTER $, LINKED ACCOUNTS, VOLUME ×, PRICE MOVE, SHARP RECORD, FRESH
> WALLET}. The active tile list is in `image_tiles`. Don't waste tweet
> characters listing tile facts unless they're load-bearing for the lede.

Stage-4 payload gains `image_tiles: ["clock", "cluster_total", ...]`.
Existing rules (banned phrases, lede shapes, length, polyspotter URL)
stay untouched.

## Fallbacks

- **Hero fetcher fails.** Existing `render_chart_for_alert` fallback to
  wallet_record_card kicks in (already works). Tile selection runs
  against the new hero.
- **Tile fetcher fails (e.g. baseline volume missing).** Drop that tile,
  slide remaining tiles up. Grid renders with 1–2 tiles or even 0; that's
  fine.
- **Zero tiles pass thresholds.** Fall back to single-chart 1200×675
  layout. The grid only ships when there's density to show.
- **Hero = "none".** No image at all (same as today). The grid never
  ships without a real hero.

## Polish

- Tile typography: same weight/family as the hero number, scaled to ~80pt
  (vs. the hero's ~200pt). Label below in MUTED at ~24pt.
- Accent color rule: ACCENT (green) for positive-direction facts (volume
  up, price up, win record), neutral FG for everything else. Avoid an
  all-green wall.
- Tile dividers: 1px MUTED between slots. 1px MUTED between hero column
  and tile column.
- No tile borders, no boxes. Same flat dark-card aesthetic as today.

## Testing

- Existing chart renderer tests keep working — `render_X(data) -> bytes`
  signatures are unchanged.
- Unit tests for `select_tiles`: pure function over `facts_bundle` +
  hero_type, table-driven. Cases: hero-dedup (sharp record tile suppressed
  when hero is wallet_record_card), threshold gating (CLUSTER $ dropped
  when total_usd < $25k), priority ordering (CLOCK first when set), zero
  tiles pass.
- One smoke test for `compose_chart` per hero type: assemble with a
  representative facts_bundle, assert output is a valid 1200×675 PNG.
- Extend `storybot/render_all_charts.py` to render a few representative
  grid combinations for visual sanity-checking before ship.

## Out of scope

- Mini-chart tiles (sparklines, mini-bars inside a tile slot). Pure stat
  tiles ship first; if a specific tile feels weak in practice, that one
  fact can be promoted to a mini-chart in a follow-up.
- LLM curation of tiles. Tiles are deterministic; the LLM keeps its
  existing job of picking the hero only.
- Replacing the single-chart layout in articlebot. articlebot keeps
  using the current `render_chart_for_alert` path (unchanged).
- Variable-shape grids (1+2, 2×2, etc.). Layout is fixed: hero left,
  3 tiles right.
