"use client";

import { useState } from "react";

export default function ShareButton({ url, title, text, compact = false, iconOnly = false }) {
  const [copied, setCopied] = useState(false);

  async function handleShare(e) {
    e.stopPropagation();

    // Try native share API first (mobile browsers)
    if (typeof navigator !== "undefined" && navigator.share) {
      try {
        await navigator.share({
          title: title || "PolySpotter",
          text: text || "",
          url,
        });
        return;
      } catch (err) {
        // AbortError = user dismissed, fall through to clipboard
        if (err.name !== "AbortError") {
          // Fall through to clipboard
        }
      }
    }

    // Clipboard fallback
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      const input = document.createElement("input");
      input.value = url;
      document.body.appendChild(input);
      input.select();
      document.execCommand("copy");
      document.body.removeChild(input);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }

  const shareIcon = (
    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 12v8a2 2 0 002 2h12a2 2 0 002-2v-8M16 6l-4-4-4 4M12 2v13" />
    </svg>
  );

  return (
    <button
      onClick={handleShare}
      className="inline-flex items-center gap-1.5 rounded-lg text-xs transition-colors"
      style={{
        padding: iconOnly ? "4px" : compact ? "4px 8px" : "6px 14px",
        background: iconOnly ? "transparent" : "var(--surface-1)",
        color: copied ? "var(--accent)" : "var(--text-muted)",
        border: iconOnly ? "none" : "1px solid var(--border-subtle)",
      }}
      aria-label="Share"
    >
      {iconOnly ? (
        shareIcon
      ) : (
        <>
          {copied ? "\u2713 Copied" : shareIcon}
          {!copied && <span className="hidden sm:inline">Share</span>}
        </>
      )}
    </button>
  );
}
