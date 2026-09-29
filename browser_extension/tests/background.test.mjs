// Run with: node --test "browser_extension/tests/*.test.mjs"
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const here = dirname(fileURLToPath(import.meta.url));
const source = (name) => readFileSync(join(here, "..", name), "utf8");

function loadBackground({ storage = {}, granted = true } = {}) {
  const listeners = [];
  const fetchCalls = [];
  const context = {
    console,
    URL,
    Number,
    fetch: async (url, init) => {
      fetchCalls.push({ url, init });
      return { ok: true, json: async () => ({ inserted: 1 }) };
    },
    chrome: {
      runtime: { id: "ext-id", onMessage: { addListener: (fn) => listeners.push(fn) } },
      storage: { local: { get: async () => storage } },
      permissions: { contains: async () => granted },
    },
  };
  context.importScripts = (name) => vm.runInContext(source(name), context);
  vm.createContext(context);
  vm.runInContext(source("background.js"), context);
  const dispatch = (message, sender) =>
    new Promise((resolve) => {
      const result = listeners[0](message, sender, resolve);
      if (result === false) return;
    });
  return { dispatch, fetchCalls };
}

const marketplaceSender = { id: "ext-id", tab: { id: 1 }, url: "https://www.wildberries.ru/catalog/1/detail.aspx" };
const configured = { apiOrigin: "https://stats.example.com", apiKey: "bsk_x", accountId: "shop-1" };

test("rejects messages without the protocol version", async () => {
  const { dispatch, fetchCalls } = loadBackground({ storage: configured });
  const response = await dispatch({ type: "serp_positions", data: [] }, marketplaceSender);
  assert.equal(response.ok, false);
  assert.equal(fetchCalls.length, 0);
});

test("rejects senders that are not marketplace pages", async () => {
  const { dispatch, fetchCalls } = loadBackground({ storage: configured });
  const response = await dispatch(
    { v: 1, type: "serp_positions", data: [] },
    { id: "ext-id", tab: { id: 1 }, url: "https://evil.example.com/" },
  );
  assert.equal(response.ok, false);
  assert.equal(response.error, "untrusted sender");
  assert.equal(fetchCalls.length, 0);
});

test("maps competitor prices to the API contract and uses the configured account", async () => {
  const { dispatch, fetchCalls } = loadBackground({ storage: configured });
  const response = await dispatch(
    {
      v: 1,
      type: "competitor_price",
      data: { marketplace: "wb", product_id: 42, competitor_name: "X", price_rub: 990, price_with_discount_rub: null },
    },
    marketplaceSender,
  );
  assert.equal(response.ok, true);
  const [call] = fetchCalls;
  assert.equal(call.url, "https://stats.example.com/api/v1/extension/competitor-price");
  assert.equal(call.init.headers["X-API-Key"], "bsk_x");
  const [item] = JSON.parse(call.init.body);
  assert.equal(item.competitor_product_id, "42");
  assert.equal(item.account_id, "shop-1");
  assert.equal(item.price_with_discount_rub, null);
});

test("refuses to call the API without the host permission", async () => {
  const { dispatch, fetchCalls } = loadBackground({ storage: configured, granted: false });
  const response = await dispatch(
    { v: 1, type: "product_overlay", data: { marketplace: "wb", product_id: 7 } },
    marketplaceSender,
  );
  assert.equal(response.ok, false);
  assert.match(response.error, /permission/);
  assert.equal(fetchCalls.length, 0);
});
