export function MetricsGrid({ data }) {
  console.log("METRICS GRID DATA:", data);

  if (!data) return <div>NO DATA</div>;

import { useState } from "react";

import { getCompany } from "../api";
import SearchBar from "../components/SearchBar";
import { MetricsGrid } from "../components/MetricsGrid";

export default function Overview() {
  const [data, setData] = useState(null);

  const loadStock = async (ticker) => {
    try {
      const res = await getCompany(ticker);
      console.log("API RESPONSE:", res);
      setData(res);
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div style={styles.page}>
      
      <header style={styles.header}>
        <div>
          <div style={styles.logo}>MK StockLens</div>
          <div style={styles.sub}>analytics terminal</div>
        </div>

        <div style={styles.search}>
          <SearchBar onSearch={loadStock} />
        </div>
      </header>

      <main style={styles.main}>
        {!data && (
          <div style={styles.empty}>
            Search any ticker (AAPL, MSFT, NVDA...)
          </div>
        )}

        {data && <MetricsGrid data={data} />}
      </main>
    </div>
  );
}

const styles = {
  page: {
    minHeight: "100vh",
    background: "#050816",
    color: "white",
    fontFamily: "Inter, ui-sans-serif, system-ui",
    padding: 16,
  },

  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 40,
    paddingRight: 12,
  },

  logo: {
    fontSize: 28,
    fontWeight: 800,
    letterSpacing: "-1px",
  },

  sub: {
    color: "#6b7280",
    fontSize: 10,
    marginTop: 4,
  },

  search: {
    width: 320,
  },

  main: {
    marginTop: 20,
  },

  empty: {
    marginTop: 80,
    color: "#64748b",
    fontSize: 16,
    textAlign: "center",
  },
};