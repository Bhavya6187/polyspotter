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
  if (rating === 0) return <span className="text-xs text-gray-400">—</span>;

  const barColors = [
    // index 0 unused, 1-5 map to rating levels
    "",
    "bg-gray-400 dark:bg-gray-500",
    "bg-amber-400 dark:bg-amber-500",
    "bg-amber-500 dark:bg-amber-400",
    "bg-orange-500 dark:bg-orange-400",
    "bg-red-500 dark:bg-red-400",
  ];

  return (
    <div className="flex items-center gap-1.5" title={`${LABELS[rating - 1]} signal (${maxScore?.toFixed(1)})`}>
      <div className="flex items-end gap-0.5">
        {[1, 2, 3, 4, 5].map((level) => (
          <div
            key={level}
            className={`w-1 rounded-sm ${
              level <= rating
                ? barColors[rating]
                : "bg-gray-200 dark:bg-gray-700"
            }`}
            style={{ height: `${6 + level * 3}px` }}
          />
        ))}
      </div>
    </div>
  );
}
