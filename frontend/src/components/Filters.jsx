import { useState, useEffect, useRef } from "react";

export default function Filters({ categories, filters, onFilterChange }) {
  const [localMinScore, setLocalMinScore] = useState(filters.minScore);
  const [localWallet, setLocalWallet] = useState(filters.wallet);
  const debounceRef = useRef(null);

  useEffect(() => {
    setLocalMinScore(filters.minScore);
    setLocalWallet(filters.wallet);
  }, [filters.minScore, filters.wallet]);

  function debounced(key, value) {
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      onFilterChange({ ...filters, [key]: value });
    }, 300);
  }

  return (
    <div className="flex flex-wrap items-center gap-4 rounded-lg bg-gray-800 p-4">
      <label className="flex items-center gap-2 text-sm text-gray-400">
        Min Score
        <input
          type="number"
          step="0.5"
          min="0"
          value={localMinScore}
          onChange={(e) => {
            const v = e.target.value;
            setLocalMinScore(v);
            debounced("minScore", v);
          }}
          className="w-20 rounded bg-gray-900 px-2 py-1 text-gray-100 outline-none focus:ring-1 focus:ring-gray-600"
        />
      </label>

      <label className="flex items-center gap-2 text-sm text-gray-400">
        Category
        <select
          value={filters.category}
          onChange={(e) => onFilterChange({ ...filters, category: e.target.value })}
          className="rounded bg-gray-900 px-2 py-1 text-gray-100 outline-none focus:ring-1 focus:ring-gray-600"
        >
          <option value="">All Categories</option>
          {categories.map((c) => {
            const name = typeof c === "string" ? c : c.category;
            return (
              <option key={name} value={name}>
                {name}
              </option>
            );
          })}
        </select>
      </label>

      <label className="flex items-center gap-2 text-sm text-gray-400">
        Wallet
        <input
          type="text"
          placeholder="Search wallet address..."
          value={localWallet}
          onChange={(e) => {
            const v = e.target.value;
            setLocalWallet(v);
            debounced("wallet", v);
          }}
          className="w-56 rounded bg-gray-900 px-2 py-1 text-gray-100 outline-none focus:ring-1 focus:ring-gray-600"
        />
      </label>
    </div>
  );
}
