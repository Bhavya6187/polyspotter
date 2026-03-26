const LABELS = ["Weak", "Low", "Medium", "Strong", "Very Strong"];

export function scoreToRating(maxScore) {
  if (maxScore == null || maxScore <= 0) return 0;
  if (maxScore < 6) return 1;
  if (maxScore < 10) return 2;
  if (maxScore < 15) return 3;
  if (maxScore < 25) return 4;
  return 5;
}

export default function StrengthMeter({ maxScore }) {
  const rating = scoreToRating(maxScore);
  if (rating === 0) return <span className="text-xs" style={{ color: 'var(--text-muted)' }}>&mdash;</span>;

  const colors = [
    "",
    "var(--text-muted)",
    "#f59e0b",
    "#f97316",
    "var(--accent)",
    "var(--accent)",
  ];

  const fillColor = colors[rating];

  return (
    <div className="flex items-center gap-1.5 shrink-0" title={`${LABELS[rating - 1]} signal (${maxScore?.toFixed(1)})`}>
      <div className="flex items-end gap-[3px]">
        {[1, 2, 3, 4, 5].map((level) => (
          <div
            key={level}
            className="rounded-sm transition-all duration-300"
            style={{
              width: '3px',
              height: `${5 + level * 3}px`,
              background: level <= rating ? fillColor : 'var(--border)',
              boxShadow: level <= rating && rating >= 4 ? `0 0 4px ${fillColor}` : 'none',
            }}
          />
        ))}
      </div>
    </div>
  );
}
