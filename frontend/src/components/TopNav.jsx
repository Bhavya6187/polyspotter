"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import CommandPalette from "./CommandPalette";
import ThemeToggle from "./ThemeToggle";

const LINKS = [
  { href: "/", label: "Live" },
  { href: "/signals", label: "Signals" },
  { href: "/discover", label: "Discover" },
  { href: "/watchlist", label: "Watchlist" },
];

export default function TopNav({ tags = [], topWallets = [] }) {
  const pathname = usePathname();
  return (
    <header
      className="hidden md:flex items-center justify-between gap-4 px-6 py-4 border-b"
      style={{ borderColor: "var(--border-subtle)", background: "var(--surface-0)" }}
    >
      <Link href="/" className="flex items-center gap-2">
        <span
          className="grid place-items-center"
          style={{
            width: 28, height: 28, borderRadius: 8,
            background: "linear-gradient(135deg, var(--accent), var(--accent-hover))",
            boxShadow: "0 0 14px var(--accent-subtle)",
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
            <path d="M4 17L9 12L13 16L20 7" stroke="#05080f" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </span>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 15, fontWeight: 700, letterSpacing: -0.3, color: "var(--text-primary)" }}>
          polyspotter
        </span>
      </Link>

      <nav className="flex items-center gap-1">
        {LINKS.map((l) => {
          const active = pathname === l.href;
          return (
            <Link
              key={l.href}
              href={l.href}
              className="px-3 py-2 rounded-lg text-sm font-semibold"
              style={{
                color: active ? "var(--text-primary)" : "var(--text-secondary)",
                background: active ? "var(--surface-2)" : "transparent",
              }}
            >
              {l.label}
            </Link>
          );
        })}
      </nav>

      <div className="flex items-center gap-2">
        <CommandPalette tags={tags} topWallets={topWallets} />
        <ThemeToggle />
      </div>
    </header>
  );
}
