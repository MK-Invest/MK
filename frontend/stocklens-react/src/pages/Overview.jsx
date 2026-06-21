import { useState } from "react";
import { getCompany, getValuation } from "../api";
import SearchBar from "../components/SearchBar";
import { StockDashboard } from "../components/StockDashboard";

export default function Overview() {
  const [data, setData] = useState(null);
  const [ticker, setTicker] = useState(null);
  const [loading, setLoading] = useState(false);
  const [recalculating, setRecalculating] = useState(false);
  const [error, setError] = useState(null);

  const applyValuation = (company, valuation) => ({
    ...company,
    valuation: valuation?.valuation,
    scenarios: valuation?.scenarios,
    valuationHistorical: valuation?.historical,
    valuationRating: valuation?.rating,
    valuationRatingColor: valuation?.rating_color,
    valuationRequiredReturn: valuation?.required_return,
    valuationYears: valuation?.years,
  });

  const loadStock = async (newTicker) => {
    setLoading(true);
    setError(null);
    try {
      const [company, valuation] = await Promise.all([
        getCompany(newTicker),
        getValuation(newTicker),
      ]);

      if (company?.detail) {
        setError(`Ticker nenalezen: ${newTicker}`);
        setData(null);
        setTicker(null);
      } else {
        setData(applyValuation(company, valuation));
        setTicker(newTicker);
      }
    } catch (e) {
      setError("Chyba při načítání dat.");
      setData(null);
      setTicker(null);
    } finally {
      setLoading(false);
    }
  };

  // Přepočet valuace se zachovanými fundamentals (company data),
  // jen nové scénářové předpoklady (bear/base/bull revenue_cagr atd.)
  const recalculate = async (overrides) => {
    if (!ticker || !data) return;
    setRecalculating(true);
    setError(null);
    try {
      const valuation = await getValuation(ticker, overrides);
      setData((prev) => applyValuation(prev, valuation));
    } catch (e) {
      setError("Chyba při přepočtu valuace.");
    } finally {
      setRecalculating(false);
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
      {data && !loading && (
        <StockDashboard
          data={data}
          onRecalculate={recalculate}
          recalculating={recalculating}
        />
      )}

    </div>
  );
}
