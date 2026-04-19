import DigestBlock from "./rail/DigestBlock";
import SharpestWallets from "./rail/SharpestWallets";
import WatchlistBlock from "./rail/WatchlistBlock";
import LiveTicker from "./rail/LiveTicker";

export default function RightRail() {
  return (
    <aside className="hidden md:block w-[320px] sticky top-4 space-y-3 self-start">
      <DigestBlock />
      <SharpestWallets />
      <WatchlistBlock />
      <LiveTicker />
    </aside>
  );
}
