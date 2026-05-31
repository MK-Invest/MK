import { useState } from "react";
import { getCompany } from "../api";
import SearchBar from "../components/SearchBar";
import { StockDashboard } from "../components/StockDashboard";

export default function Overview() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const loadStock = async (ticker) => {
    setLoading(true);
    setError(null);
    try {
      const res = await getCompany(ticker);
      if (res?.detail) {
        setError(`Ticker nenalezen: ${ticker}`);
        setData(null);
      } else {
        setData(res);
      }
    } catch (e) {
      setError("Chyba při načítání dat.");
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ backgroundColor: "#0A0E1A", minHeight: "100vh", color: "white" }}>

      {/* Search bar fixně nahoře */}
      <div style={{
        position: "sticky",
        top: 0,
        zIndex: 100,
        background: "#0A0E1A",
        borderBottom: "1px solid #1E293B",
        padding: "12px 32px",
        display: "flex",
        alignItems: "center",
        gap: 16,
      }}>
        <span style={{
          fontSize: 14,
          fontWeight: 700,
          letterSpacing: "0.12em",
          color: "#38BDF8",
          fontFamily: "'IBM Plex Mono', monospace",
          whiteSpace: "nowrap",
        }}>
          STOCK<span style={{ color: "#64748B" }}>LENS</span>
        </span>
        <SearchBar onSearch={loadStock} />
      </div>

      {/* Stavy */}
      {loading && (
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "center",
          height: "60vh", color: "#38BDF8", fontSize: 14,
          fontFamily: "'IBM Plex Mono', monospace", letterSpacing: "0.1em",
        }}>
          ⟳ Načítám data...
        </div>
      )}

      {error && !loading && (
        <div style={{
          margin: "40px 32px", padding: "16px 20px",
          background: "#1F0A0A", border: "1px solid #7F1D1D",
          borderRadius: 8, color: "#F87171", fontSize: 13,
          fontFamily: "'IBM Plex Mono', monospace",
        }}>
          {error}
        </div>
      )}

      {!data && !loading && !error && (
        <div style={{
          display: "flex", flexDirection: "column",
          alignItems: "center", justifyContent: "center",
          height: "60vh", gap: 12,
          fontFamily: "'IBM Plex Mono', monospace",
        }}>
          <div style={{ fontSize: 13, color: "#334155", letterSpacing: "0.1em" }}>
            ZADEJ TICKER
          </div>
          <div style={{ fontSize: 11, color: "#1E293B" }}>
            např. AAPL · PFE · MSFT · NVDA
          </div>
        </div>
      )}

      {/* Dashboard */}
      {data && !loading && <StockDashboard data={data} />}

    </div>
  );
}
