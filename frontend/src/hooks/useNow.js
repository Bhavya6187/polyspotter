"use client";

import { useEffect, useState } from "react";

// Current time for rendering relative ("3m ago") and time-to-resolution
// values in SSR'd client components.
//
// Returns null during SSR and the first client render (hydration), then
// Date.now() once mounted, refreshed every `tickMs`. Callers render a
// server-safe form (absolute UTC timestamp, or nothing) while it is null so
// server and client markup match and React does not report a hydration
// mismatch.
export function useNow(tickMs = 30000) {
  const [now, setNow] = useState(null);

  useEffect(() => {
    setNow(Date.now());
    if (!tickMs) return undefined;
    const id = setInterval(() => setNow(Date.now()), tickMs);
    return () => clearInterval(id);
  }, [tickMs]);

  return now;
}
