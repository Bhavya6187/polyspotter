import TopNav from "./TopNav";
import MobileTabBar from "./MobileTabBar";

export default function AppShell({ tags = [], topWallets = [], children }) {
  return (
    <div className="min-h-screen">
      <TopNav tags={tags} topWallets={topWallets} />
      <main className="mx-auto max-w-[1440px] pb-32 md:pb-12">
        {children}
      </main>
      <MobileTabBar />
    </div>
  );
}
