const BASE_URL = import.meta.env.VITE_API_URL;

export async function getCompany(ticker) {
  const url = `${BASE_URL}/company/${ticker}`;

  console.log("FETCH:", url);

  const res = await fetch(url);

  console.log("STATUS:", res.status);

  const data = await res.json();

  console.log("RESPONSE:", data);

  return data;
}

export async function getValuation(ticker, body = {}) {
  const url = `${BASE_URL}/valuation/${ticker}`;

  console.log("FETCH VALUATION:", url);

  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      required_return: 0.10,
      years: 3,
      ...body,
    }),
  });

  console.log("VALUATION STATUS:", res.status);

  const data = await res.json();

  console.log("VALUATION RESPONSE:", data);

  if (!res.ok) {
    throw new Error(data?.detail || "Valuation request failed");
  }

  return data;
}
