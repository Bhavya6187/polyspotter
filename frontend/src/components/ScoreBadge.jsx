export default function ScoreBadge({ score }) {
  let bg = "bg-green-900 text-green-300";
  if (score >= 7) {
    bg = "bg-red-900 text-red-300";
  } else if (score >= 4) {
    bg = "bg-yellow-900 text-yellow-300";
  }

  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-sm font-semibold ${bg}`}>
      {score.toFixed(1)}
    </span>
  );
}
