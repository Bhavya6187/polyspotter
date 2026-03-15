const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

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

export function fetchAlerts({ page, perPage, minScore, wallet, category } = {}) {
  return request("/api/alerts", {
    page,
    per_page: perPage,
    min_score: minScore || undefined,
    wallet: wallet || undefined,
    category: category || undefined,
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

export function fetchCategories() {
  return request("/api/categories");
}

export function fetchHealth() {
  return request("/api/health");
}
