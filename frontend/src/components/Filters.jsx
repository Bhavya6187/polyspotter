export default function Filters({ tags, filters, onFilterChange }) {
  return (
    <div className="flex flex-wrap items-center gap-4 rounded-lg bg-gray-100 p-4 dark:bg-gray-800">
      <label className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
        Tag
        <select
          value={filters.tag}
          onChange={(e) => onFilterChange({ ...filters, tag: e.target.value })}
          className="rounded bg-white px-2 py-1 text-gray-900 outline-none focus:ring-1 focus:ring-gray-300 dark:bg-gray-900 dark:text-gray-100 dark:focus:ring-gray-600"
        >
          <option value="">All Tags</option>
          {tags.map((t) => {
            const name = typeof t === "string" ? t : t.tag;
            return (
              <option key={name} value={name}>
                {name}
              </option>
            );
          })}
        </select>
      </label>
    </div>
  );
}
