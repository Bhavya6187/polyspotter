"use client";

import { useState } from "react";

export default function ShareButton({ url, compact = false }) {
  const [copied, setCopied] = useState(false);

  async function handleShare() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback for non-HTTPS contexts
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

  return (
    <button
      onClick={handleShare}
      className="inline-flex items-center gap-1.5 rounded-lg text-xs transition-colors"
      style={{
        padding: compact ? "4px 8px" : "6px 14px",
        background: "var(--surface-1)",
        color: copied ? "var(--accent)" : "var(--text-muted)",
        border: "1px solid var(--border-subtle)",
      }}
    >
      {copied ? "\u2713 Copied" : "\ud83d\udce4 Share"}
    </button>
  );
}
