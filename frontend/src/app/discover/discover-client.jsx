"use client";
import { useRouter } from "next/navigation";
import AppShell from "../../components/AppShell";
import TopicTiles from "../../components/TopicTiles";

export default function DiscoverClient({ topics, tags, topWallets }) {
  const router = useRouter();
  return (
    <AppShell tags={tags} topWallets={topWallets}>
      <div className="px-4 md:px-6 pt-6">
        <h1 className="text-3xl md:text-4xl font-bold tracking-tight" style={{ color: "var(--text-primary)" }}>Discover</h1>
        <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
          Signal activity by topic · last 24h
        </div>
      </div>
      <TopicTiles topics={topics} onSelect={(name) => router.push(`/signals?topic=${encodeURIComponent(name)}`)} />
    </AppShell>
  );
}
