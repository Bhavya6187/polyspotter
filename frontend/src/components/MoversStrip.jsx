import MoverCard from "./MoverCard";

export default function MoversStrip({ movers = [] }) {
  if (!movers.length) return null;
  return (
    <section className="mt-6 px-4 md:px-6">
      <div className="flex items-end justify-between mb-3">
        <h3 className="text-base md:text-lg font-bold" style={{ color: "var(--text-primary)" }}>
          Live movers
        </h3>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>See all →</span>
      </div>
      <div className="flex gap-2 overflow-x-auto no-scrollbar -mx-4 px-4 md:mx-0 md:px-0 pb-2">
        {movers.map((m, i) => (
          <MoverCard key={m.condition_id} mover={m} pulseDelay={i * 1.2} />
        ))}
      </div>
    </section>
  );
}
