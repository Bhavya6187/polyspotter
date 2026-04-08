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

export function fetchTrackRecord(days = 7) {
  return request("/api/signals/track-record", { days });
}

export function fetchResolvedSignals(limit = 5) {
  return request("/api/signals/resolved", { limit });
}

export function fetchVolumeSpikes(limit = 5) {
  return request("/api/flow/volume-spikes", { limit });
}

export function fetchActiveWallets(limit = 5) {
  return request("/api/flow/active-wallets", { limit });
}

export function fetchTopMovers(limit = 6) {
  return request("/api/markets/top-movers", { limit });
}

export function fetchBriefing(since = null) {
  return request("/api/briefing", { since: since || undefined });
}
