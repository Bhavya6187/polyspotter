"use client";

import { useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import AppShell from "../components/AppShell";
import DigestBanner from "../components/DigestBanner";
import Top3Hero from "../components/Top3Hero";
import MoversStrip from "../components/MoversStrip";
import TopicTiles from "../components/TopicTiles";
import TopicFilterChips from "../components/TopicFilterChips";
import SignalFeed from "../components/SignalFeed";
import RightRail from "../components/RightRail";

function HomeInner({ topSignals, movers, topics, topWallets, tags }) {
  const search = useSearchParams();
  const [topic, setTopic] = useState(search.get("topic") || "All");

  return (
    <AppShell tags={tags} topWallets={topWallets}>
      <div className="grid md:grid-cols-[minmax(0,1fr)_320px] gap-6 px-0 md:px-6 pt-2">
        <div>
          <div className="px-4 md:px-0">
            <DigestBanner />
          </div>
          <Top3Hero signals={topSignals} />
          <MoversStrip movers={movers} />
          {/* Topic tiles: desktop-only grid; mobile uses chips below */}
          <div className="hidden md:block">
            <TopicTiles topics={topics} onSelect={setTopic} />
          </div>
          <TopicFilterChips topics={topics} active={topic} onChange={setTopic} />
          <SignalFeed topic={topic} />
        </div>
        <RightRail />
      </div>
    </AppShell>
  );
}

export default function HomeClient(props) {
  // useSearchParams requires Suspense boundary in Next 15
  return (
    <Suspense fallback={null}>
      <HomeInner {...props} />
    </Suspense>
  );
}
