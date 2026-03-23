/**
 * Shows live price vs alert-time price and estimated payout.
 *
 * Props:
 *   alertPrice  — price at time of alert (0–1)
 *   currentPrice — live midpoint price (0–1)
 *   outcome     — outcome name (e.g., "Gonzaga Bulldogs")
 *   compact     — if true, single-line layout
 */
export default function PriceMovement({ alertPrice, currentPrice, outcome, compact }) {
  if (alertPrice == null || currentPrice == null || currentPrice <= 0) return null;

  const alertCents = Math.round(alertPrice * 100);
  const currentCents = Math.round(currentPrice * 100);
  const deltaCents = currentCents - alertCents;
  const returnPct = currentPrice < 1 ? Math.round(((1 - currentPrice) / currentPrice) * 100) : 0;

  const isUp = deltaCents > 0;
  const isDown = deltaCents < 0;

  const deltaColor = isUp
    ? "text-green-500 dark:text-green-400"   // price went up = bullish
    : isDown
      ? "text-red-500 dark:text-red-400"     // price went down = bearish
      : "text-gray-400 dark:text-gray-500";

  const arrow = isUp ? "\u2191" : isDown ? "\u2193" : "";

  if (compact) {
    return (
      <span className="inline-flex items-center gap-1 text-xs">
        <span className="text-gray-400 dark:text-gray-500">{alertCents}&cent;</span>
        <span className="text-gray-400 dark:text-gray-600">&rarr;</span>
        <span className="font-medium text-gray-700 dark:text-gray-200">{currentCents}&cent;</span>
        {deltaCents !== 0 && (
          <span className={deltaColor}>
            {arrow}{Math.abs(deltaCents)}&cent;
          </span>
        )}
      </span>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      {/* Price movement */}
      <div className="flex items-center gap-1.5 text-sm">
        <span className="text-gray-500 dark:text-gray-400">
          {alertCents}&cent;
        </span>
        <span className="text-gray-400 dark:text-gray-600">&rarr;</span>
        <span className="font-semibold text-gray-800 dark:text-gray-100">
          {currentCents}&cent;
        </span>
        {deltaCents !== 0 && (
          <span className={`text-xs font-medium ${deltaColor}`}>
            ({arrow}{Math.abs(deltaCents)}&cent;)
          </span>
        )}
      </div>

      {/* Payout estimate */}
      {currentPrice < 0.99 && (
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Pay {currentCents}&cent; &rarr; win $1.00
          {returnPct > 0 && (
            <span className="ml-1 text-green-600 dark:text-green-400">
              ({returnPct}% return)
            </span>
          )}
        </p>
      )}
    </div>
  );
}
