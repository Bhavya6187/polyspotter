import Script from "next/script";
import { JetBrains_Mono, DM_Sans } from "next/font/google";
import "./globals.css";
import { themeScript } from "./theme-script";

const jbMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
  variable: "--font-jb-mono",
});

const dmSans = DM_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  style: ["normal", "italic"],
  display: "swap",
  variable: "--font-dm-sans",
});

const GA_ID = "G-CDJT9HKLCR";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

const jsonLd = {
  "@context": "https://schema.org",
  "@type": "WebSite",
  name: "PolySpotter",
  url: SITE_URL,
  description:
    "Track whale trades and smart money on Polymarket. PolySpotter surfaces large bets from sharp bettors, coordinated flow, and high-conviction positioning.",
  publisher: {
    "@type": "Organization",
    name: "PolySpotter",
    url: SITE_URL,
  },
};

export const metadata = {
  metadataBase: new URL(SITE_URL),
  alternates: {
    canonical: "/",
  },
  title: {
    default: "PolySpotter — Polymarket Whale Trades & Smart Money Alerts",
    template: "%s | PolySpotter",
  },
  description:
    "Track whale trades and smart money on Polymarket in real time. PolySpotter surfaces large bets, sharp bettors, and coordinated flow across prediction markets — updated every minute.",
  keywords: [
    "Polymarket",
    "smart money",
    "prediction markets",
    "whale trades",
    "sharp bettors",
    "polymarket alerts",
    "polymarket trades",
    "polymarket whale tracker",
    "prediction market signals",
    "polymarket biggest bets",
  ],
  robots: {
    index: true,
    follow: true,
  },
  openGraph: {
    title: "PolySpotter — Polymarket Whale Trades & Smart Money Alerts",
    description:
      "Real-time alerts for notable Polymarket trades: whale bets, sharp bettors, and coordinated flow.",
    url: SITE_URL,
    siteName: "PolySpotter",
    type: "website",
    locale: "en_US",
    images: [
      {
        url: "/og-default.png",
        width: 1200,
        height: 630,
        alt: "PolySpotter — Polymarket Whale Trade Tracker",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "PolySpotter — Polymarket Whale Trades & Smart Money Alerts",
    description:
      "Real-time alerts for notable Polymarket trades: whale bets, sharp bettors, and coordinated flow.",
    images: ["/og-default.png"],
  },
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "32x32", type: "image/x-icon" },
      { url: "/favicon.svg", type: "image/svg+xml" },
    ],
  },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={`${jbMono.variable} ${dmSans.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
      </head>
      <body className="min-h-screen" style={{ background: 'var(--surface-0)', color: 'var(--text-primary)' }}>
        {children}
        <Script
          src={`https://www.googletagmanager.com/gtag/js?id=${GA_ID}`}
          strategy="afterInteractive"
        />
        <Script id="google-analytics" strategy="afterInteractive">
          {`
            window.dataLayer = window.dataLayer || [];
            function gtag(){dataLayer.push(arguments);}
            gtag('js', new Date());
            gtag('config', '${GA_ID}');
          `}
        </Script>
      </body>
    </html>
  );
}
