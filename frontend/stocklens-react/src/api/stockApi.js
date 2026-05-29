// src/api/stockApi.js

export async function getStock(ticker) {
  const res = await fetch(`http://localhost:8000/company/${ticker}`);
  if (!res.ok) throw new Error("API error");
  return res.json();
}