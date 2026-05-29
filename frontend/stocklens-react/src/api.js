const BASE_URL = "http://localhost:8000";

export async function getCompany(ticker) {
  const url = `${BASE_URL}/company/${ticker}`;

  console.log("FETCH:", url);

  const res = await fetch(url);

  console.log("STATUS:", res.status);

  const data = await res.json();

  console.log("RESPONSE:", data);

  return data;
}