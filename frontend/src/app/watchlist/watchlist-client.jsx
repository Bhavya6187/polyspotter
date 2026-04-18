"use client";
import AppShell from "../../components/AppShell";
import WatchlistBlock from "../../components/rail/WatchlistBlock";

export default function WatchlistClient({ tags, topWallets }) {
  return (
    <AppShell tags={tags} topWallets={topWallets}>
      <div className="px-4 md:px-6 pt-6">
        <h1 className="text-3xl md:text-4xl font-bold tracking-tight" style={{ color: "var(--text-primary)" }}>Watchlist</h1>
        <div className="text-xs mt-1 mb-4" style={{ color: "var(--text-muted)" }}>
          Your saved markets (stored locally on this device)
        </div>
        <div className="max-w-xl">
          <WatchlistBlock full />
        </div>
      </div>
    </AppShell>
  );
}
