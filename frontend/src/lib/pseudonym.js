/**
 * Deterministic wallet pseudonyms from address + tier.
 */

export function walletPseudonym(address, tier) {
  if (!address) return "Unknown";
  const prefix = tier?.prefix || "Wallet";
  const short = address.startsWith("0x") ? address.slice(2, 7) : address.slice(0, 5);
  return `${prefix}_0x${short}`;
}

export function shortenAddress(address) {
  if (!address) return "";
  return `${address.slice(0, 6)}...${address.slice(-4)}`;
}
