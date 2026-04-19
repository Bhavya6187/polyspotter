export default function StrengthBars({ rating = 0, className = "" }) {
  const color =
    rating >= 4 ? "var(--accent)" :
    rating >= 3 ? "#f97316" :
    rating >= 2 ? "var(--warning)" :
                  "var(--text-muted)";
  return (
    <div
      role="meter"
      aria-valuemin={1}
      aria-valuemax={5}
      aria-valuenow={rating}
      aria-label={`Signal strength ${rating} of 5`}
      className={`inline-flex items-end gap-[2px] h-[14px] ${className}`}
    >
      {[1,2,3,4,5].map((i) => (
        <span
          key={i}
          style={{
            width: 3,
            height: 3 + i * 2,
            borderRadius: 1,
            background: i <= rating ? color : "var(--border)",
            boxShadow: i <= rating && rating >= 4 ? `0 0 4px ${color}` : "none",
            transition: "all 180ms",
          }}
        />
      ))}
    </div>
  );
}
