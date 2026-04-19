export default function WalletAvatar({ wallet, size = 26 }) {
  if (!wallet) return null;
  const c = wallet.color || "#00c26a";
  return (
    <div
      title={wallet.addr}
      style={{
        width: size, height: size,
        borderRadius: size >= 32 ? "50%" : 7,
        display: "inline-grid", placeItems: "center",
        background: `linear-gradient(135deg, ${c}, ${c}88)`,
        color: "#fff",
        fontFamily: "var(--font-mono)",
        fontWeight: 700,
        fontSize: size * 0.34,
        letterSpacing: 0.3,
        flexShrink: 0,
      }}
    >
      {(wallet.alias || "??").slice(0, 2)}
    </div>
  );
}
