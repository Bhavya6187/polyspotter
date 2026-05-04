"use client";

import { useState, useEffect, useCallback } from "react";

const STORAGE_KEY = "polyspotter_engage_toast";
const DISMISS_TTL_MS = 2 * 24 * 60 * 60 * 1000;
const TIME_TRIGGER_MS = 20_000;
const SENTINEL_ID = "top-three-end-sentinel";

function readSuppression() {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function writeSuppression(value) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {}
}

function isCurrentlySuppressed() {
  const stored = readSuppression();
  if (!stored) return false;
  if (typeof stored.followedAt === "number") return true;
  if (typeof stored.dismissedAt === "number") {
    return Date.now() - stored.dismissedAt < DISMISS_TTL_MS;
  }
  return false;
}

export default function EngagementToast() {
  const [visible, setVisible] = useState(false);

  const handleClose = useCallback(() => {
    writeSuppression({ dismissedAt: Date.now() });
    setVisible(false);
  }, []);

  const handleFollow = useCallback(() => {
    writeSuppression({ followedAt: Date.now() });
    setVisible(false);
  }, []);

  const handleFeedback = useCallback(() => {
    writeSuppression({ dismissedAt: Date.now() });
    setVisible(false);
  }, []);

  useEffect(() => {
    if (isCurrentlySuppressed()) return undefined;

    let alreadyShown = false;
    const show = () => {
      if (alreadyShown) return;
      alreadyShown = true;
      setVisible(true);
    };

    const timer = setTimeout(show, TIME_TRIGGER_MS);

    let observer = null;
    const sentinel = document.getElementById(SENTINEL_ID);
    if (sentinel && typeof IntersectionObserver !== "undefined") {
      observer = new IntersectionObserver(
        (entries) => {
          for (const entry of entries) {
            if (entry.isIntersecting) {
              show();
              break;
            }
          }
        },
        { threshold: 0 }
      );
      observer.observe(sentinel);
    }

    return () => {
      clearTimeout(timer);
      if (observer) observer.disconnect();
    };
  }, []);

  useEffect(() => {
    if (!visible) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") {
        writeSuppression({ dismissedAt: Date.now() });
        setVisible(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [visible]);

  if (!visible) return null;

  return (
    <div
      role="region"
      aria-label="Follow PolySpotter"
      className="animate-toast-in fixed z-50 w-[calc(100%-2rem)] max-w-[320px] rounded-xl p-4 shadow-lg"
      style={{
        bottom: "1.5rem",
        right: "1.5rem",
        background: "var(--surface-card)",
        border: "1px solid var(--border)",
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="currentColor"
            className="h-4 w-4"
            style={{ color: "var(--text-primary)" }}
            aria-hidden="true"
          >
            <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
          </svg>
          <span
            className="text-sm font-semibold"
            style={{ color: "var(--text-primary)" }}
          >
            Follow @polyspotter
          </span>
        </div>
        <button
          type="button"
          onClick={handleClose}
          aria-label="Dismiss"
          className="shrink-0 rounded p-1 transition-opacity hover:opacity-70"
          style={{ color: "var(--text-muted)" }}
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            className="h-3.5 w-3.5"
            aria-hidden="true"
          >
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>

      <p className="mt-2 text-xs" style={{ color: "var(--text-secondary)" }}>
        We&rsquo;re constantly sharing today&rsquo;s top alerts.
      </p>

      <a
        href="https://x.com/polyspotter"
        target="_blank"
        rel="noopener noreferrer"
        onClick={handleFollow}
        className="mt-3 flex w-full items-center justify-center rounded-md px-3 py-2 text-sm font-medium transition-colors"
        style={{
          background: "var(--accent)",
          color: "#ffffff",
        }}
      >
        Follow on X
      </a>

      <div
        className="my-3 h-px"
        style={{ background: "var(--border-subtle)" }}
        aria-hidden="true"
      />

      <a
        href="mailto:feedback@polyspotter.com"
        onClick={handleFeedback}
        className="block text-xs transition-opacity hover:opacity-80"
        style={{ color: "var(--text-muted)" }}
      >
        Got thoughts? Send feedback →
      </a>
    </div>
  );
}
