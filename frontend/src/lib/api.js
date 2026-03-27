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

export function fetchMarketAlerts({ page, perPage, minScore, wallet, tag, resolvesWithin } = {}) {
  return request("/api/alerts/by-market", {
    page,
    per_page: perPage,
    min_score: minScore || undefined,
    wallet: wallet || undefined,
    tag: tag || undefined,
    resolves_within: resolvesWithin || undefined,
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
