// BormoStats background script — SERP monitoring and competitor price tracking
const API_BASE = "https://your-instance/api/v1/extension";

async function sendPositions(positions) {
  const { apiUrl, apiKey } = await chrome.storage.sync.get(["apiUrl", "apiKey"]);
  if (!apiUrl || !positions.length) return;
  try {
    await fetch(`${apiUrl}/positions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(apiKey ? { "X-API-Key": apiKey } : {}) },
      body: JSON.stringify(positions),
    });
  } catch (e) {
    console.error("BormoStats: failed to send positions", e);
  }
}

async function sendCompetitorPrice(data) {
  const { apiUrl, apiKey } = await chrome.storage.sync.get(["apiUrl", "apiKey"]);
  if (!apiUrl) return;
  try {
    await fetch(`${apiUrl}/competitor-price`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(apiKey ? { "X-API-Key": apiKey } : {}) },
      body: JSON.stringify([data]),
    });
  } catch (e) {
    console.error("BormoStats: failed to send competitor price", e);
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "serp_positions") {
    sendPositions(message.data);
  }
  if (message.type === "competitor_price") {
    sendCompetitorPrice(message.data);
  }
});
