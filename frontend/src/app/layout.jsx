import Script from "next/script";
import "./globals.css";
import { themeScript } from "./theme-script";

const GA_ID = "G-CDJT9HKLCR";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

const jsonLd = {
  "@context": "https://schema.org",
  "@type": "WebSite",
  name: "PolySpotter",
  url: SITE_URL,
  description:
    "Track smart money on Polymarket. PolySpotter surfaces large bets from sharp bettors, coordinated flow, and high-conviction positioning.",
};

export const metadata = {
  metadataBase: new URL(SITE_URL),
  alternates: {
    canonical: "/",
  },
  title: {
    default: "PolySpotter — Follow the Smart Money on Polymarket",
    template: "%s | PolySpotter",
  },
  description:
    "Track smart money on Polymarket. PolySpotter surfaces large bets from sharp bettors, coordinated flow, and high-conviction positioning - updated in real time.",
  keywords: [
    "Polymarket",
    "smart money",
    "prediction markets",
    "whale trades",
    "sharp bettors",
    "polymarket alerts",
    "polymarket trades",
  ],
  robots: {
    index: true,
    follow: true,
  },
  openGraph: {
    title: "PolySpotter — Follow the Smart Money on Polymarket",
    description:
      "Real-time alerts for notable Polymarket trades: Large bets, sharp bettors, and coordinated flow.",
    url: SITE_URL,
    siteName: "PolySpotter",
    type: "website",
    locale: "en_US",
  },
  twitter: {
    card: "summary",
    title: "PolySpotter — Follow the Smart Money on Polymarket",
    description:
      "Real-time alerts for notable Polymarket trades: Large bets, sharp bettors, and coordinated flow.",
  },
  icons: {
    icon: "/favicon.svg",
  },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
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
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
      </head>
      <body className="min-h-screen bg-gray-50 text-gray-900 dark:bg-gray-950 dark:text-gray-100">
        {children}
      </body>
    </html>
  );
}
