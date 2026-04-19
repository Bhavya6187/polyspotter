"use client";

import { useState, useEffect, useRef } from "react";

export default function HowWePickPopover() {
  const [open, setOpen] = useState(false);
  const containerRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    function onClickAway(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
      }
    }
    function onEsc(e) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onClickAway);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onClickAway);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="text-[11px] uppercase tracking-wider transition-opacity hover:opacity-80"
        style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}
        aria-expanded={open}
      >
        How we pick these &rarr;
      </button>
      {open && (
        <div
          role="dialog"
          className="absolute right-0 top-full z-20 mt-2 w-80 rounded-lg p-3 shadow-lg"
          style={{
            background: "var(--surface-card)",
            border: "1px solid var(--border)",
            color: "var(--text-secondary)",
          }}
        >
          <div
            className="mb-1 text-xs font-bold uppercase tracking-wider"
            style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}
          >
            How we pick these
          </div>
          <p className="text-xs leading-relaxed">
            We rank every notable trade by edge, urgency, and wallet quality. The top 3 always span three angles: a sharp-wallet conviction bet, coordinated flow across multiple wallets, and a timing edge near resolution.
          </p>
        </div>
      )}
    </div>
  );
}
