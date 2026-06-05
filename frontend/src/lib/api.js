const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function request(path, params = {}) {
  const url = new URL(path, BASE_URL);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, value);
    }
  });
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export function fetchAlerts({ page, perPage, minScore, wallet, tag } = {}) {
  return request("/api/alerts", {
    page,
    per_page: perPage,
    min_score: minScore || undefined,
    wallet: wallet || undefined,
    tag: tag || undefined,
  });
}

export function fetchMarketAlerts({ page, perPage, minScore, wallet, tag, resolvesWithin, q, groupEvents } = {}) {
  return request("/api/alerts/by-market", {
    page,
    per_page: perPage,
    min_score: minScore || undefined,
    wallet: wallet || undefined,
    tag: tag || undefined,
    resolves_within: resolvesWithin || undefined,
    q: q || undefined,
    group_events: groupEvents ? "true" : undefined,
  });
}

export function fetchAlertDetail(alertId) {
  return request(`/api/alerts/${alertId}`);
}

export function fetchWalletProfile(walletAddress) {
  return request(`/api/wallets/${walletAddress}`);
}

export function fetchStrategies() {
  return request("/api/strategies");
}

export function fetchTags() {
  return request("/api/tags");
}

export function fetchMarketLive(conditionId) {
  return request(`/api/market/${conditionId}/live`);
}

export function fetchSportOverlay(conditionId, { title, eventSlug, tags } = {}) {
  const params = new URLSearchParams();
  if (title) params.set("title", title);
  if (eventSlug) params.set("event_slug", eventSlug);
  for (const t of tags || []) params.append("tag", t);
  const url = new URL(`/api/market/${conditionId}/overlay`, BASE_URL);
  url.search = params.toString();
  return fetch(url).then((res) => {
    if (res.status === 404) return null;       // no overlay for this market
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
  });
}

export function fetchHealth() {
  return request("/api/health");
}

export function fetchSpotlight() {
  return request("/api/spotlight");
}

export function fetchTopThree() {
  return request("/api/top3");
}

export function fetchScoreboard() {
  return request("/api/scoreboard");
}

export function subscribeEmail({ email, source, hp } = {}) {
  const url = new URL("/api/subscribe", BASE_URL);
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, source, hp }),
  }).then(async (res) => {
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `API error: ${res.status}`);
    }
    return res.json();
  });
}

export function fetchResolvingSoon() {
  return request("/api/resolving-soon");
}

export function fetchTheses(page = 1, perPage = 5) {
  return request("/api/theses", { page, per_page: perPage });
}

export function fetchPriceHistory(conditionId, range = "7d") {
  return request(`/api/market/${conditionId}/price-history`, { range });
}

export function fetchMarketHolders(conditionId) {
  return request(`/api/market/${conditionId}/holders`);
}

export function fetchMarketTheses(conditionId) {
  return request(`/api/market/${conditionId}/theses`);
}

export function fetchEvent(slug) {
  return request(`/api/event/${encodeURIComponent(slug)}`);
}

export function fetchEvents({ page, perPage, minMarkets, minAlerts, includeResolved, tag } = {}) {
  return request("/api/events", {
    page,
    per_page: perPage,
    min_markets: minMarkets,
    min_alerts: minAlerts,
    include_resolved: includeResolved,
    tag: tag || undefined,
  });
}
