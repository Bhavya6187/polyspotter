"use client";
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import AppShell from "../../components/AppShell";
import SignalFeed from "../../components/SignalFeed";

function Inner({ tags, topWallets }) {
  const s = useSearchParams();
  const topic = s.get("topic") || "All";
  return (
    <AppShell tags={tags} topWallets={topWallets}>
      <div className="px-4 md:px-6 pt-6">
        <h1 className="text-3xl md:text-4xl font-bold tracking-tight" style={{ color: "var(--text-primary)" }}>Signals</h1>
        <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>Live stream of notable trades</div>
      </div>
      <SignalFeed topic={topic} />
    </AppShell>
  );
}

export default function SignalsClient(props) {
  return <Suspense fallback={null}><Inner {...props} /></Suspense>;
}
