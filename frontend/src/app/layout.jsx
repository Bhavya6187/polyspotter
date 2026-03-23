import "./globals.css";
import { themeScript } from "./theme-script";

export const metadata = {
  title: {
    default: "PolySpotter — Follow the Smart Money on Polymarket",
    template: "%s | PolySpotter",
  },
  description:
    "Track smart money on Polymarket. PolySpotter surfaces large bets from sharp bettors, coordinated flow, and high-conviction positioning.",
  openGraph: {
    title: "PolySpotter — Follow the Smart Money on Polymarket",
    description:
      "Real-time alerts for notable Polymarket trades: $3,000+ bets, sharp bettors, and coordinated flow.",
    type: "website",
  },
  icons: {
    icon: "/favicon.svg",
  },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-screen bg-gray-50 text-gray-900 dark:bg-gray-950 dark:text-gray-100">
        {children}
      </body>
    </html>
  );
}
