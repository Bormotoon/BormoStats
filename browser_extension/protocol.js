// Versioned message protocol shared by the content script and the service worker.
// Content scripts never see the API key or call the API: they send typed messages,
// the service worker validates them and talks to the configured BormoStats origin.
/* exported BORMOSTATS_PROTOCOL */
var BORMOSTATS_PROTOCOL = Object.freeze({
  version: 1,
  types: Object.freeze({
    serpPositions: "serp_positions",
    competitorPrice: "competitor_price",
    productOverlay: "product_overlay",
  }),
  marketplaceHosts: Object.freeze([/\.wildberries\.(ru|by)$/, /\.ozon\.ru$/]),
  maxBatch: 500,
});
