"use client";

import { useState } from "react";
import { subscribeEmail } from "../lib/api";

// Email signup form. `source` tags where the signup came from (e.g. "hero",
// "footer"). Includes an off-screen honeypot field to deter bots.
export default function EmailCapture({ source = "home" }) {
  const [email, setEmail] = useState("");
  const [hp, setHp] = useState(""); // honeypot — must stay empty for humans
  const [status, setStatus] = useState("idle"); // idle | loading | done | error
  const [error, setError] = useState("");

  async function onSubmit(e) {
    e.preventDefault();
    if (status === "loading") return;
    setStatus("loading");
    setError("");
    try {
      await subscribeEmail({ email, source, hp });
      setStatus("done");
      setEmail("");
    } catch (err) {
      setStatus("error");
      setError(err?.message || "Something went wrong — try again.");
    }
  }

  if (status === "done") {
    return (
      <p className="text-sm" style={{ color: "var(--bullish)" }}>
        ✓ You&rsquo;re on the list — we&rsquo;ll send the smart-money brief.
      </p>
    );
  }

  return (
    <form
      onSubmit={onSubmit}
      className="flex flex-col gap-2 sm:flex-row sm:items-center"
    >
      {/* Honeypot: visually hidden, off-screen; bots fill it, humans don't. */}
      <input
        type="text"
        name="company"
        tabIndex={-1}
        autoComplete="off"
        aria-hidden="true"
        value={hp}
        onChange={(e) => setHp(e.target.value)}
        style={{ position: "absolute", left: "-9999px", width: 1, height: 1, opacity: 0 }}
      />
      <input
        type="email"
        required
        placeholder="you@email.com"
        aria-label="Email address"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        className="min-w-0 flex-1 rounded-lg px-3 py-2 text-sm"
        style={{
          background: "var(--surface-1)",
          border: "1px solid var(--border)",
          color: "var(--text-primary)",
        }}
      />
      <button
        type="submit"
        disabled={status === "loading"}
        className="rounded-lg px-4 py-2 text-sm font-bold transition-opacity disabled:opacity-50"
        style={{ background: "var(--accent)", color: "var(--surface-0)" }}
      >
        {status === "loading" ? "Joining…" : "Get the brief"}
      </button>
      {status === "error" && (
        <span className="text-xs" style={{ color: "var(--bearish)" }} role="alert">
          {error}
        </span>
      )}
    </form>
  );
}
