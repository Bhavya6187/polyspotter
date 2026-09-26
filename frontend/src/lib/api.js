import { API_URL as BASE_URL } from "./apiBase";

async function request(path, params = {}) {
  const url = new URL(path, BASE_URL);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, value);
    }
  });
  const res = await fetch(url);
  if (!res.ok) {
    const err = new Error(`API error: ${res.status} ${res.statusText}`);
    err.status = res.status;
    throw err;
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
  return request(`/api/alerts/${encodeURIComponent(alertId)}`);
}

export function fetchWalletProfile(walletAddress) {
  return request(`/api/wallets/${encodeURIComponent(walletAddress)}`);
}

export function fetchStrategies() {
  return request("/api/strategies");
}

export function fetchTags() {
  return request("/api/tags");
}

export function fetchMarketLive(conditionId) {
  return request(`/api/market/${encodeURIComponent(conditionId)}/live`);
}

export function fetchSportOverlay(conditionId, { title, eventSlug, tags } = {}) {
  const params = new URLSearchParams();
  if (title) params.set("title", title);
  if (eventSlug) params.set("event_slug", eventSlug);
  for (const t of tags || []) params.append("tag", t);
  const url = new URL(`/api/market/${encodeURIComponent(conditionId)}/overlay`, BASE_URL);
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

export function fetchDigests() {
  return request("/api/digests");
}

export function fetchDigest(date) {
  return request(`/api/digest/${encodeURIComponent(date)}`);
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
  return request(`/api/market/${encodeURIComponent(conditionId)}/price-history`, { range });
}

export function fetchMarketHolders(conditionId) {
  return request(`/api/market/${encodeURIComponent(conditionId)}/holders`);
}

export function fetchMarketTheses(conditionId) {
  return request(`/api/market/${encodeURIComponent(conditionId)}/theses`);
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
