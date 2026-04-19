"use client";
import { useEffect, useState } from "react";
import { fetchDigest } from "../lib/api";

const KEY = "polyspotter.lastVisit.v1";

export function useDigest() {
  const [digest, setDigest] = useState(null);
  const [since, setSince] = useState(null);

  useEffect(() => {
    let last;
    try { last = window.localStorage.getItem(KEY); } catch { last = null; }
    if (!last) last = new Date(Date.now() - 24*60*60*1000).toISOString();
    setSince(last);
    fetchDigest(last).then(setDigest).catch(() => setDigest(null));

    const bump = () => { try { window.localStorage.setItem(KEY, new Date().toISOString()); } catch {} };
    window.addEventListener("pagehide", bump);
    return () => window.removeEventListener("pagehide", bump);
  }, []);

  return { digest, since };
}
