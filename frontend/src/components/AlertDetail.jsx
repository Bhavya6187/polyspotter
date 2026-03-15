import { useEffect, useState } from "react";
import { fetchAlertDetail, fetchWalletProfile } from "../api";
import ScoreBadge from "./ScoreBadge";

function formatStrategy(name) {
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function truncateAddress(addr) {
  if (!addr) return "\u2014";
  if (addr.length <= 12) return addr;
  return `${addr.slice(0, 6)}...${addr.slice(-4)}`;
}

function relativeTime(dateStr) {
  if (!dateStr) return "\u2014";
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diffSec = Math.floor((now - then) / 1000);
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}

const usdFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export default function AlertDetail({ alertId, wallet, alertType }) {
  const [detail, setDetail] = useState(null);
  const [walletProfile, setWalletProfile] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    const promises = [fetchAlertDetail(alertId)];
    if (wallet) {
      promises.push(fetchWalletProfile(wallet).catch(() => null));
    } else {
      promises.push(Promise.resolve(null));
    }

    Promise.all(promises).then(([alertData, walletData]) => {
      if (cancelled) return;
      setDetail(alertData);
      setWalletProfile(walletData);
      setLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, [alertId, wallet]);

  if (loading) {
    return (
      <tr>
        <td colSpan="6" className="bg-gray-900/80 px-6 py-8 text-center text-gray-400">
          Loading details...
        </td>
      </tr>
    );
  }

  if (!detail) return null;

  const signals = detail.signals || [];
  const trades = detail.trades || [];

  return (
    <tr>
      <td colSpan="6" className="border-b border-gray-700 bg-gray-900/80 p-0">
        <div className="p-6">
          {/* Type & Wallet meta */}
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <span
              className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                alertType === "cluster"
                  ? "bg-purple-900 text-purple-300"
                  : "bg-blue-900 text-blue-300"
              }`}
            >
              {alertType ?? "composite"}
            </span>
            {alertType === "cluster" && trades.length > 0 ? (
              <span className="text-sm text-gray-400">
                {new Set(trades.map((t) => t.wallet)).size} wallets
              </span>
            ) : wallet ? (
              <span className="font-mono text-sm text-gray-400">
                {truncateAddress(wallet)}
              </span>
            ) : null}
          </div>

          {/* LLM Summary */}
          {detail.llm_summary && (
            <div className="mb-6 rounded-lg border border-amber-700/50 bg-amber-900/20 p-4">
              <h3 className="mb-1 text-sm font-semibold uppercase tracking-wider text-amber-400">
                AI Analysis
              </h3>
              <p className="text-sm text-amber-100">{detail.llm_summary}</p>
            </div>
          )}
          <div className="flex flex-col gap-6 lg:flex-row">
            {/* Signals */}
            <div className="flex-1">
              <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-400">
                Signals
              </h3>
              <div className="flex flex-col gap-3">
                {signals.length === 0 && (
                  <p className="text-sm text-gray-500">No signals.</p>
                )}
                {signals.map((sig, i) => (
                  <div
                    key={i}
                    className="rounded-lg bg-gray-800 p-4"
                  >
                    <div className="mb-1 flex items-center gap-2">
                      <span className="text-sm font-medium text-gray-200">
                        {formatStrategy(sig.strategy)}
                      </span>
                      <ScoreBadge score={sig.severity ?? 0} />
                    </div>
                    <p className="text-sm text-gray-400">{sig.headline}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Wallet Profile */}
            {walletProfile && (
              <div className="w-full lg:w-72">
                <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-400">
                  Wallet Profile
                </h3>
                <div className="rounded-lg bg-gray-800 p-4">
                  <dl className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <dt className="text-gray-400">Win Rate</dt>
                      <dd className="text-gray-100">
                        {walletProfile.win_rate != null
                          ? `${(walletProfile.win_rate * 100).toFixed(1)}%`
                          : "\u2014"}
                      </dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-gray-400">Total P&L</dt>
                      <dd
                        className={
                          walletProfile.total_pnl >= 0
                            ? "text-green-400"
                            : "text-red-400"
                        }
                      >
                        {walletProfile.total_pnl != null
                          ? usdFmt.format(walletProfile.total_pnl)
                          : "\u2014"}
                      </dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-gray-400">Positions</dt>
                      <dd className="text-gray-100">
                        {walletProfile.total_positions ?? 0} /{" "}
                        {walletProfile.closed_positions ?? 0}
                      </dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-gray-400">Times Flagged</dt>
                      <dd className="text-gray-100">
                        {walletProfile.times_flagged ?? 0}
                      </dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-gray-400">First Seen</dt>
                      <dd className="text-gray-100">
                        {walletProfile.first_seen_at
                          ? new Date(walletProfile.first_seen_at).toLocaleDateString()
                          : "\u2014"}
                      </dd>
                    </div>
                  </dl>
                </div>
              </div>
            )}
          </div>

          {/* Trades sub-table */}
          {trades.length > 0 && (
            <div className="mt-6">
              <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-400">
                Trades
              </h3>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-gray-700 text-xs uppercase text-gray-500">
                      <th className="px-3 py-2">Tx Hash</th>
                      <th className="px-3 py-2">Wallet</th>
                      <th className="px-3 py-2">Outcome</th>
                      <th className="px-3 py-2">Side</th>
                      <th className="px-3 py-2">USD Value</th>
                      <th className="px-3 py-2">Price</th>
                      <th className="px-3 py-2">Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((t, i) => (
                      <tr
                        key={i}
                        className="border-b border-gray-800/50"
                      >
                        <td className="px-3 py-2 font-mono">
                          {truncateAddress(t.transaction_hash)}
                        </td>
                        <td className="px-3 py-2 font-mono">
                          {truncateAddress(t.wallet)}
                        </td>
                        <td className="px-3 py-2">{t.outcome ?? "\u2014"}</td>
                        <td className="px-3 py-2">
                          <span
                            className={
                              t.side === "BUY"
                                ? "text-green-400"
                                : "text-red-400"
                            }
                          >
                            {t.side}
                          </span>
                        </td>
                        <td className="px-3 py-2">
                          {t.usd_value != null
                            ? usdFmt.format(t.usd_value)
                            : "\u2014"}
                        </td>
                        <td className="px-3 py-2">
                          {t.price != null ? t.price.toFixed(2) : "\u2014"}
                        </td>
                        <td className="px-3 py-2 text-gray-400">
                          {relativeTime(t.trade_timestamp)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {detail.market_url && (
                <a
                  href={detail.market_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-3 inline-block text-sm text-blue-400 hover:text-blue-300"
                >
                  View on Polymarket &rarr;
                </a>
              )}
            </div>
          )}
        </div>
      </td>
    </tr>
  );
}
