"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/",          label: "Home",      d: "M3 12l9-9 9 9M5 10v10a2 2 0 002 2h3v-6h4v6h3a2 2 0 002-2V10" },
  { href: "/signals",   label: "Signals",   d: "M2 12h4l3-8 4 16 3-8h4" },
  { href: "/discover",  label: "Discover",  d: "M12 3a9 9 0 100 18 9 9 0 000-18zM16 8l-2 6-6 2 2-6 6-2z" },
  { href: "/watchlist", label: "Watchlist", d: "M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z" },
];

export default function MobileTabBar() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Main"
      className="md:hidden fixed inset-x-0 bottom-0 z-30 flex justify-around pt-2 pb-safe"
      style={{
        background: "rgba(5,8,15,0.82)",
        backdropFilter: "blur(20px) saturate(180%)",
        WebkitBackdropFilter: "blur(20px) saturate(180%)",
        borderTop: "1px solid var(--border)",
      }}
    >
      {TABS.map((t) => {
        const active = pathname === t.href;
        const color = active ? "var(--accent)" : "var(--text-muted)";
        return (
          <Link
            key={t.href}
            href={t.href}
            aria-label={t.label}
            aria-current={active ? "page" : undefined}
            className="flex flex-col items-center gap-1 px-3 py-1.5"
            style={{ color }}
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
              <path d={t.d} stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            <span style={{ fontSize: 10, fontWeight: 600, letterSpacing: 0.1 }}>{t.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
