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

export function fetchMarketAlerts({ page, perPage, minScore, wallet, tag, resolvesWithin, q } = {}) {
  return request("/api/alerts/by-market", {
    page,
    per_page: perPage,
    min_score: minScore || undefined,
    wallet: wallet || undefined,
    tag: tag || undefined,
    resolves_within: resolvesWithin || undefined,
    q: q || undefined,
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

export function fetchHealth() {
  return request("/api/health");
}

export function fetchSpotlight() {
  return request("/api/spotlight");
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

export function fetchBasketballData(conditionId, { title = "", event_slug = "" } = {}) {
  return request(`/api/market/${conditionId}/basketball`, { title, event_slug });
}

export function fetchCricketData(conditionId, { title = "", event_slug = "" } = {}) {
  return request(`/api/market/${conditionId}/cricket`, { title, event_slug });
}

export function fetchSignals({ topic, limit = 20, offset = 0, minRating, resolvesWithin } = {}) {
  return request("/api/signals", {
    topic: topic || undefined,
    limit,
    offset,
    min_rating: minRating || undefined,
    resolves_within: resolvesWithin || undefined,
  });
}

export function fetchTopSignals() {
  return request("/api/signals/top");
}

export function fetchMovers(limit = 6) {
  return request("/api/markets/movers", { limit });
}

export function fetchTopics() {
  return request("/api/topics");
}

export function fetchDigest(since) {
  return request("/api/digest", { since });
}

export function fetchTickerRecent(limit = 20) {
  return request("/api/ticker/recent", { limit });
}

export function fetchMarketCard(conditionId) {
  return request(`/api/markets/${conditionId}/card`);
}
