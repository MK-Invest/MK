import { useState, useRef, useEffect } from "react";

const BASE_URL = "https://mk-m01x.onrender.com";

export default function SearchBar({ onSearch }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);

  const debounceRef = useRef(null);
  const wrapRef = useRef(null);

  // Zavření dropdownu při kliknutí mimo
  useEffect(() => {
    const handler = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Debounced search
  const handleChange = (e) => {
    const val = e.target.value;
    setQuery(val);

    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (val.trim().length < 1) {
      setResults([]);
      setOpen(false);
      return;
    }

    debounceRef.current = setTimeout(async () => {
      setLoading(true);

      try {
        const res = await fetch(
          `${BASE_URL}/search?query=${encodeURIComponent(val.trim())}`
        );
        const data = await res.json();

        // 🔥 DEDUPE: 1 ticker = 1 výsledek (NASDAQ priorita)
        const map = new Map();

        (Array.isArray(data) ? data : []).forEach((item) => {
          const key = item.symbol;

          if (!map.has(key)) {
            map.set(key, item);
          } else {
            // preferuj NASDAQ (nebo US listing)
            const existing = map.get(key);

            const score = (x) =>
              (x.exchange === "NASDAQ" ? 3 : 0) +
              (x.market === "United States" ? 2 : 0);

            if (score(item) > score(existing)) {
              map.set(key, item);
            }
          }
        });

        setResults(Array.from(map.values()));
        setOpen(true);
      } catch (err) {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 300);
  };

  const handleSelect = (item) => {
    const ticker = item.symbol;
    setQuery(ticker);
    setResults([]);
    setOpen(false);
    onSearch(ticker);
  };

  const handleSubmit = () => {
    const val = query.trim().toUpperCase();
    if (!val) return;

    setOpen(false);
    onSearch(val);
  };

  const handleKey = (e) => {
    if (e.key === "Enter") handleSubmit();
    if (e.key === "Escape") setOpen(false);
  };

  return (
    <div
      ref={wrapRef}
      style={{
        position: "relative",
        display: "flex",
        gap: 8,
        flex: 1,
        maxWidth: 480,
      }}
    >
      <div style={{ position: "relative", flex: 1 }}>
        <input
          value={query}
          onChange={handleChange}
          onKeyDown={handleKey}
          onFocus={() => results.length > 0 && setOpen(true)}
          placeholder="Ticker nebo název firmy (AAPL, Apple...)"
          style={{
            width: "100%",
            padding: "8px 12px",
            background: "#0F172A",
            border: "1px solid #1E3A5F",
            borderRadius: 6,
            color: "#E2E8F0",
            fontSize: 13,
            fontFamily: "inherit",
            outline: "none",
            boxSizing: "border-box",
          }}
        />

        {/* DROPDOWN */}
        {open && results.length > 0 && (
          <div
            style={{
              position: "absolute",
              top: "calc(100% + 4px)",
              left: 0,
              right: 0,
              background: "#0F172A",
              border: "1px solid #1E3A5F",
              borderRadius: 6,
              zIndex: 1000,
              maxHeight: 320,
              overflowY: "auto",
            }}
          >
            {results.map((item, i) => (
              <div
                key={`${item.symbol}-${item.exchange}-${i}`}
                onClick={() => handleSelect(item)}
                style={{
                  padding: "10px 14px",
                  cursor: "pointer",
                  borderBottom:
                    i < results.length - 1 ? "1px solid #1E293B" : "none",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: 8,
                }}
                onMouseEnter={(e) =>
                  (e.currentTarget.style.background = "#1E293B")
                }
                onMouseLeave={(e) =>
                  (e.currentTarget.style.background = "transparent")
                }
              >
                {/* LEFT */}
                <div>
                  <span
                    style={{
                      fontSize: 13,
                      fontWeight: 600,
                      color: "#38BDF8",
                      fontFamily: "monospace",
                    }}
                  >
                    {item.symbol}
                  </span>

                  {item.name && (
                    <span
                      style={{
                        fontSize: 12,
                        color: "#94A3B8",
                        marginLeft: 8,
                      }}
                    >
                      {item.name}
                    </span>
                  )}
                </div>

                {/* RIGHT */}
                <div style={{ textAlign: "right", flexShrink: 0 }}>
                  {item.exchange && (
                    <span
                      style={{
                        fontSize: 11,
                        background: "#1E3A5F",
                        color: "#7DD3FC",
                        padding: "2px 6px",
                        borderRadius: 3,
                      }}
                    >
                      {item.exchange}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <button
        onClick={handleSubmit}
        style={{
          padding: "8px 16px",
          background: "#1E3A5F",
          border: "1px solid #2563EB",
          borderRadius: 6,
          color: "#38BDF8",
          fontSize: 13,
          fontFamily: "inherit",
          cursor: "pointer",
          whiteSpace: "nowrap",
        }}
      >
        Hledat
      </button>

      {loading && (
        <div
          style={{
            position: "absolute",
            right: 80,
            top: "50%",
            transform: "translateY(-50%)",
            fontSize: 11,
            color: "#475569",
          }}
        >
          ⟳
        </div>
      )}
    </div>
  );
}