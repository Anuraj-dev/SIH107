import { useState, useMemo } from "react";
import { CURATED_STANDARDS, type StandardItem } from "./standardsData";
import { CatalogIcon, SearchIcon, ExternalLinkIcon, ChatIcon } from "./icons";

interface StandardsDirectoryProps {
  onSelectQuery: (query: string) => void;
}

export default function StandardsDirectory({ onSelectQuery }: StandardsDirectoryProps) {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("All");

  const categories = useMemo(() => {
    const cats = new Set<string>();
    CURATED_STANDARDS.forEach((s) => cats.add(s.category));
    return ["All", ...Array.from(cats)];
  }, []);

  const filtered = useMemo(() => {
    const rawQ = search.trim().toLowerCase();
    const normQ = rawQ.replace(/[^a-z0-9]/g, "");

    return CURATED_STANDARDS.filter((s) => {
      const matchCat = category === "All" || s.category === category;
      if (!rawQ) return matchCat;

      const normIs = s.is_number.toLowerCase().replace(/[^a-z0-9]/g, "");
      const matchIs = (normQ.length > 0 && normIs.includes(normQ)) || s.is_number.toLowerCase().includes(rawQ);
      const matchText =
        s.title_en.toLowerCase().includes(rawQ) ||
        s.title_hi.toLowerCase().includes(rawQ) ||
        s.scope_en.toLowerCase().includes(rawQ) ||
        s.scheme.toLowerCase().includes(rawQ) ||
        (s.keywords && s.keywords.some((k) => k.toLowerCase().includes(rawQ) || rawQ.includes(k.toLowerCase())));

      return matchCat && (matchIs || matchText);
    });
  }, [search, category]);

  return (
    <div className="directory-container">
      <div className="directory-header">
        <div className="view-header">
          <div className="admin-icon-box">
            <CatalogIcon size={20} />
          </div>
          <div>
            <h2 className="directory-title">Indian Standards Directory</h2>
            <p className="directory-subtitle">
              Curated authoritative repository of National Standards governing public safety, consumer goods, and industrial quality.
            </p>
          </div>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="directory-controls">
        <div className="search-box">
          <SearchIcon className="search-box-icon" />
          <label className="sr-only" htmlFor="standards-search">Search standards</label>
          <input
            id="standards-search"
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by IS number (e.g. IS 10500), product, or scope…"
            className="search-input"
          />
          {search && (
            <button
              type="button"
              className="search-clear-btn"
              onClick={() => setSearch("")}
              aria-label="Clear search"
            >
              ×
            </button>
          )}
        </div>

        <div className="category-chips" role="group" aria-label="Filter standards by sector">
          {categories.map((cat) => (
            <button
              key={cat}
              type="button"
              aria-pressed={category === cat}
              className={`cat-chip${category === cat ? " active" : ""}`}
              onClick={() => setCategory(cat)}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {/* Grid of Standards */}
      <div className="standards-grid">
        {filtered.length === 0 ? (
          <div className="empty-state-box">
            <p className="empty-state-title">No standards match your filter.</p>
            <p className="empty-state-sub">Try adjusting the search query or category filter above.</p>
          </div>
        ) : (
          filtered.map((s: StandardItem) => (
            <div key={s.is_number} className="standard-card">
              <div className="card-top">
                <div className="standard-id-badge">
                  <span className="is-num">{s.is_number}</span>
                  <span className="is-year">:{s.year}</span>
                </div>
                <span className={`status-pill ${s.status === "Active" ? "status-active" : "status-withdrawn"}`}>
                  {s.status}
                </span>
              </div>

              <h3 className="card-title-en">{s.title_en}</h3>
              <p className="card-title-hi">{s.title_hi}</p>

              <div className="scheme-tag">
                <span className="scheme-label">Scheme:</span> {s.scheme}
              </div>

              <p className="card-scope">{s.scope_en}</p>

              <div className="card-actions">
                <button
                  type="button"
                  className="btn-query-assistant"
                  onClick={() => onSelectQuery(s.sample_query)}
                  title={`Ask Assistant about ${s.is_number}`}
                >
                  <ChatIcon size={14} />
                  <span>Ask Assistant</span>
                </button>
                <a
                  href={s.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="btn-bis-portal"
                  title="View on Know Your Standard portal"
                >
                  <span>BIS Portal</span>
                  <span className="sr-only"> (opens in new tab)</span>
                  <ExternalLinkIcon size={12} />
                </a>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
