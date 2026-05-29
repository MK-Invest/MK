aimport { useState } from "react";
import { getCompany } from "../api";

import SearchBar from "../components/SearchBar";
import { CompanyHeader } from "../components/CompanyHeader";
import { MetricsGrid } from "../components/MetricsGrid";

import Charts from "../components/Charts";

export default function Overview() {
  const [data, setData] = useState(null);

  const loadStock = async (ticker) => {
    const res = await getCompany(ticker);

    console.log("RAW API RESPONSE:", res);
    console.log("DATA KEYS:", Object.keys(res));

    setData(res);
  };

  return (
    <div style={{
      backgroundColor: "#0B0F19",
      minHeight: "100vh",
      color: "white",
      padding: 20
    }}>

      <SearchBar onSearch={loadStock} />

      {!data && (
        <div style={{ marginTop: 20, color: "#6B7280" }}>
          Zadej ticker (např. AAPL)
        </div>
      )}

      {data && (
          <>
            <CompanyHeader ticker={data.ticker ?? "N/A"} data={data} />
            <MetricsGrid data={data} />
            <Charts data={data} />
          </>
      )}

    </div>
  );
}