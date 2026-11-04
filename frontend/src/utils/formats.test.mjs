import test from "node:test";
import assert from "node:assert/strict";
import { isSafeImageUrl, buyerCardUrl } from "./formats.js";

test("isSafeImageUrl permits https, http, and data:image URLs", () => {
  assert.equal(isSafeImageUrl("https://basket-01.wbbasket.ru/vol1/part1/123.jpg"), true);
  assert.equal(isSafeImageUrl("http://cdn.example.com/img.png"), true);
  assert.equal(isSafeImageUrl("data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="), true);
});

test("isSafeImageUrl rejects javascript:, data:text/html, and malformed inputs", () => {
  assert.equal(isSafeImageUrl("javascript:alert(1)"), false);
  assert.equal(isSafeImageUrl("data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg=="), false);
  assert.equal(isSafeImageUrl("ftp://example.com/img.jpg"), false);
  assert.equal(isSafeImageUrl(""), false);
  assert.equal(isSafeImageUrl(null), false);
  assert.equal(isSafeImageUrl(undefined), false);
  assert.equal(isSafeImageUrl(12345), false);
});

test("buyerCardUrl validates IDs and encodes parameters", () => {
  assert.equal(buyerCardUrl("wb", "123456"), "https://www.wildberries.ru/catalog/123456/detail.aspx");
  assert.equal(buyerCardUrl("wb", "invalid_id"), null);
  assert.equal(buyerCardUrl("ozon", "987654"), "https://www.ozon.ru/product/987654/");
  assert.equal(buyerCardUrl("ozon", "bad_sku"), null);
  assert.equal(buyerCardUrl("ym", "SKU-100"), "https://market.yandex.ru/search?text=SKU-100");
});
