import TopicTile from "./TopicTile";

export default function TopicTiles({ topics = [], onSelect, columns = "grid-cols-2 md:grid-cols-3 xl:grid-cols-6" }) {
  if (!topics.length) return null;
  return (
    <section className="mt-6 px-4 md:px-6">
      <div className={`grid ${columns} gap-2.5 md:gap-3`}>
        {topics.map((t) => <TopicTile key={t.name} topic={t} onClick={onSelect} />)}
      </div>
    </section>
  );
}
