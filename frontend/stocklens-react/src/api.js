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