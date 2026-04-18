# Polybot Frontend

Next.js 15 web dashboard for the Polybot Polymarket trade scanner. Displays alerts, markets, wallets, tags, and cross-market theses surfaced by the scanner, with live price data, SEO-optimized market pages, and sport-specific game overlays (basketball, cricket).

## Tech Stack

- **Next.js 15** (App Router, server components)
- **React 19**
- **Tailwind CSS 4**
- **Microsoft Clarity** for analytics

## Structure

```
src/
  app/                          # Next.js App Router
    page.jsx                    # Home page (server) - loads alerts + spotlight
    home-client.jsx             # Home page client shell (filters, command palette)
    layout.jsx                  # Root layout (theme, fonts, Clarity)
    globals.css                 # Tailwind + custom CSS
    theme-script.js             # Pre-hydration theme setter
    opengraph-image.jsx         # Default OG image
    robots.js / sitemap.js      # SEO
    api/og/                     # Dynamic OG image route for shares
    alert/[id]/                 # Alert detail page
    market/[id]/                # Market page (live prices, holders, theses, sport overlays)
    wallet/[address]/           # Wallet profile page
    tag/[slug]/                 # Tag-filtered alert list
    thesis/[id]/                # Cross-market thesis detail

  components/
    AlertTable.jsx / AlertList.jsx / AlertRow.jsx / AlertDetail.jsx
    HeroSpotlight.jsx           # Featured alert on the home page
    Filters.jsx / TagFilters.jsx / SearchBar.jsx / CommandPalette.jsx
    MarketCard.jsx / MarketStats.jsx / MarketPulse.jsx / MarketTheses.jsx
    PriceChart.jsx / PriceMovement.jsx / Sparkline.jsx
    HoldersLeaderboard.jsx
    ResolvingSoonStrip.jsx / Ticker.jsx / TopicNav.jsx
    ThesisCard.jsx
    WalletBadge.jsx
    ThemeToggle.jsx / BrandMark.jsx / ShareButton.jsx / Pagination.jsx
    StrengthMeter.jsx / ScoreBadge.jsx

    # Basketball overlay
    LiveScoreBanner.jsx / BoxScore.jsx / PlayByPlayFeed.jsx
    PreGameStats.jsx / InjuryReport.jsx / SeasonSeries.jsx

    # Cricket overlay
    CricketScoreBanner.jsx / CricketScorecard.jsx
    CricketMatchInfo.jsx / CricketPreMatch.jsx / BallByBallFeed.jsx

  hooks/
    useLiveMarket.js            # Live market prices + holders polling
    useBasketballData.js        # Basketball game data polling
    useCricketData.js           # Cricket match data polling
    useSpotlight.js             # Rotating hero spotlight
    useCountdown.js             # Market-resolution countdown
    useMediaQuery.js

  lib/
    api.js                      # Backend API client
    pseudonym.js                # Wallet-address pseudonymization
    slugify.js                  # URL slug helpers
    tiers.js                    # Alert-score tier buckets
```

## Scripts

```bash
npm install         # install deps
npm run dev         # dev server (http://localhost:3000)
npm run build       # production build
npm run start       # production server
npm run lint        # Next.js / ESLint
```

## Environment

Create `.env.local`:

```bash
NEXT_PUBLIC_API_URL=https://api.polyspotter.com   # or http://localhost:8000 for local backend
NEXT_PUBLIC_CLARITY_PROJECT_ID=<optional>
```

The hosted backend at `https://api.polyspotter.com` can be used directly — no need to run the backend locally unless you're changing API behavior.

## Conventions

- **Server components by default.** Pages fetch from the backend on the server and stream into client-only sub-trees (`home-client.jsx`, hooks-driven components) for interactivity.
- **Styling**: Tailwind CSS 4 utility classes; custom tokens live in `globals.css`.
- **API client**: all backend calls go through `src/lib/api.js` — don't fetch directly from components.
- **SEO**: each route with a dynamic entity (market, wallet, tag, thesis, alert) owns its own metadata export. OG images are rendered by `api/og`.
