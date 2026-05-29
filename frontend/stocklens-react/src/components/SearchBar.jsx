import { useState } from "react";

export default function SearchBar({ onSearch }) {
  const [value, setValue] = useState("");

  const handleSearch = () => {
    const ticker = value.trim().toUpperCase();

    if (!ticker) return;

    onSearch(ticker);
  };

  return (
    <div style={styles.wrapper}>

      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Search ticker..."
        onKeyDown={(e) =>
          e.key === "Enter" && handleSearch()
        }
        style={styles.input}
      />

      <button
        onClick={handleSearch}
        style={styles.button}
      >
        Search
      </button>

    </div>
  );
}

const styles = {
  wrapper: {
    display: "flex",
    gap: 14,
  },

  input: {
    flex: 1,

    background: "#0b1020",

    border: "1px solid #1e293b",

    borderRadius: 14,

    padding: "16px 18px",

    color: "white",

    fontSize: 15,

    outline: "none",
  },

  button: {
    background:
      "linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%)",

    border: "none",

    borderRadius: 14,

    color: "white",

    padding: "0 24px",

    fontWeight: 700,

    cursor: "pointer",
  },
};