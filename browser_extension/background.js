// BormoStats service worker — the only component that holds the API key and calls the API.
importScripts("protocol.js");

const P = BORMOSTATS_PROTOCOL;

async function getConfig() {
  const { apiOrigin, apiKey, accountId } = await chrome.storage.local.get([
    "apiOrigin",
    "apiKey",
    "accountId",
  ]);
  return { apiOrigin: apiOrigin || "", apiKey: apiKey || "", accountId: accountId || "default" };
}

function isMarketplaceSender(sender) {
  if (sender.id !== chrome.runtime.id || !sender.tab || !sender.url) return false;
  try {
    const url = new URL(sender.url);
    return url.protocol === "https:" && P.marketplaceHosts.some((re) => re.test(url.hostname));
  } catch {
    return false;
  }
}

async function callApi(path, { method = "GET", body } = {}) {
  const { apiOrigin, apiKey } = await getConfig();
  if (!apiOrigin || !apiKey) throw new Error("BormoStats is not configured");
  const granted = await chrome.permissions.contains({ origins: [`${apiOrigin}/*`] });
  if (!granted) throw new Error("Host permission for the API origin was not granted");
  const response = await fetch(`${apiOrigin}${path}`, {
    method,
    credentials: "omit",
    headers: {
      "X-API-Key": apiKey,
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function toInt(value) {
  const n = Number.parseInt(value, 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}

async function handleSerpPositions(data) {
  const { accountId } = await getConfig();
  const items = (Array.isArray(data) ? data : [])
    .slice(0, P.maxBatch)
    .map((row) => ({
      account_id: accountId,
      marketplace: row.marketplace === "ozon" ? "ozon" : "wb",
      keyword: String(row.keyword || "").slice(0, 256),
      product_id: toInt(row.product_id),
      position: toInt(row.position),
      search_ts: row.search_ts,
    }))
    .filter((row) => row.keyword && row.product_id && row.position);
  if (!items.length) return { inserted: 0 };
  return callApi("/api/v1/extension/positions", { method: "POST", body: items });
}

async function handleCompetitorPrice(data) {
  const { accountId } = await getConfig();
  const price = Number(data?.price_rub);
  const productId = toInt(data?.product_id);
  if (!productId || !Number.isFinite(price) || price <= 0) return { inserted: 0 };
  const discounted = Number(data?.price_with_discount_rub);
  return callApi("/api/v1/extension/competitor-price", {
    method: "POST",
    body: [
      {
        account_id: accountId,
        marketplace: data.marketplace === "ozon" ? "ozon" : "wb",
        competitor_product_id: String(productId),
        competitor_name: String(data.competitor_name || "").slice(0, 256),
        price_rub: price,
        price_with_discount_rub: Number.isFinite(discounted) && discounted > 0 ? discounted : null,
        in_stock: data.in_stock !== false,
        snapshot_ts: data.snapshot_ts,
      },
    ],
  });
}

async function handleProductOverlay(data) {
  const productId = toInt(data?.product_id);
  const marketplace = data?.marketplace === "ozon" ? "ozon" : "wb";
  if (!productId) throw new Error("invalid product id");
  return callApi(`/api/v1/plugin/product/${marketplace}/${productId}`);
}

const HANDLERS = {
  [P.types.serpPositions]: handleSerpPositions,
  [P.types.competitorPrice]: handleCompetitorPrice,
  [P.types.productOverlay]: handleProductOverlay,
};

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.v !== P.version || !HANDLERS[message.type]) {
    sendResponse({ ok: false, error: "unsupported message" });
    return false;
  }
  if (!isMarketplaceSender(sender)) {
    sendResponse({ ok: false, error: "untrusted sender" });
    return false;
  }
  HANDLERS[message.type](message.data)
    .then((result) => sendResponse({ ok: true, result }))
    .catch((error) => {
      console.warn("BormoStats:", message.type, error.message);
      sendResponse({ ok: false, error: error.message });
    });
  return true; // async response
});
