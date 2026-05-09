"use client";

import useSportOverlay from "../../../hooks/useSportOverlay";
import { getPlugin } from "../../../sports";

// Renders the sport plugin's Banner + Header for an event page.
// Sidebar is intentionally omitted — it's market-level (price, holders) and
// doesn't make sense on an event hub spanning multiple markets.
export default function EventSportOverlay({
  conditionId,
  title,
  eventSlug,
  tags,
  initialOverlay = null,
}) {
  const { data: overlay } = useSportOverlay(conditionId, {
    initialData: initialOverlay,
    title,
    eventSlug,
    tags,
  });

  if (!overlay) return null;

  const plugin = getPlugin(overlay.sport);
  if (!plugin) return null;

  const { Banner, Header } = plugin;

  return (
    <div className="mb-6">
      {Banner && <Banner payload={overlay.payload} status={overlay.status} />}
      {Header && (
        <div className="mt-4">
          <Header payload={overlay.payload} status={overlay.status} />
        </div>
      )}
    </div>
  );
}
