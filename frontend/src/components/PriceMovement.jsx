/**
 * Shows live price vs alert-time price.
 */
export default function PriceMovement({ alertPrice, currentPrice, outcome, compact }) {
  if (alertPrice == null || currentPrice == null || currentPrice <= 0) return null;

  const alertCents = Math.round(alertPrice * 100);
  const currentCents = Math.round(currentPrice * 100);
  const deltaCents = currentCents - alertCents;
  const returnPct = currentPrice < 1 ? Math.round(((1 - currentPrice) / currentPrice) * 100) : 0;

  const isUp = deltaCents > 0;
  const isDown = deltaCents < 0;

  const deltaColor = isUp ? 'var(--bullish)' : isDown ? 'var(--bearish)' : 'var(--text-muted)';
  const arrow = isUp ? "\u2191" : isDown ? "\u2193" : "";

  if (compact) {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium" style={{ fontFamily: 'var(--font-display)' }}>
        <span style={{ color: 'var(--text-muted)' }}>{alertCents}&cent;</span>
        <span style={{ color: 'var(--border)' }}>&rarr;</span>
        <span style={{ color: 'var(--text-primary)' }}>{currentCents}&cent;</span>
        {deltaCents !== 0 && (
          <span className="font-semibold" style={{ color: deltaColor }}>
            {arrow}{Math.abs(deltaCents)}&cent;
          </span>
        )}
      </span>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-1.5 text-sm" style={{ fontFamily: 'var(--font-display)' }}>
        <span style={{ color: 'var(--text-muted)' }}>{alertCents}&cent;</span>
        <span style={{ color: 'var(--border)' }}>&rarr;</span>
        <span className="font-bold" style={{ color: 'var(--text-primary)' }}>{currentCents}&cent;</span>
        {deltaCents !== 0 && (
          <span className="text-xs font-semibold" style={{ color: deltaColor }}>
            ({arrow}{Math.abs(deltaCents)}&cent;)
          </span>
        )}
      </div>
      {currentPrice < 0.99 && (
        <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
          Pay {currentCents}&cent; &rarr; win $1.00
          {returnPct > 0 && (
            <span className="ml-1 font-semibold" style={{ color: 'var(--bullish)' }}>
              ({returnPct}% return)
            </span>
          )}
        </p>
      )}
    </div>
  );
}
