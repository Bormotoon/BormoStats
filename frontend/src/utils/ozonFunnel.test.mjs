import test from "node:test";
import assert from "node:assert/strict";
import { parseOzonFunnel, parseDay } from "./ozonFunnel.js";

test("parseDay handles various date formats correctly", () => {
  assert.equal(parseDay("2026-10-25"), "2026-10-25");
  assert.equal(parseDay("25.10.2026"), "2026-10-25");
  assert.equal(parseDay("2026/10/25"), "2026-10-25");
  assert.equal(parseDay(new Date("2026-10-25T00:00:00Z")), "2026-10-25");
  assert.equal(parseDay(46320), "2026-10-25");
});

test("parseOzonFunnel parses standard Ozon 2-tier report", () => {
  const rows = [
    ["SKU", "День", "Схема работы", "Артикул", "Товары", "", "", "", "", ""],
    [
      "",
      "",
      "",
      "",
      "",
      "Позиция в поиске и каталоге",
      "Показы всего",
      "Показы в поиске и каталоге",
      "Посещения карточки товара",
      "Добавления в корзину всего",
    ],
    ["1001", "2026-10-25", "FBO", "OFFER-1", "Product 1", 3.5, 1000, 800, 150, 20],
    ["1001", "2026-10-25", "FBO", "OFFER-1", "Product 1", 1.5, 500, 200, 50, 10],
  ];

  const parsed = parseOzonFunnel(rows, "ozon");
  assert.equal(parsed.length, 1);
  assert.equal(parsed[0].sku, "1001");
  assert.equal(parsed[0].day, "2026-10-25");
  assert.equal(parsed[0].impressions, 1500);
  assert.equal(parsed[0].search_impressions, 1000);
  assert.equal(parsed[0].clicks, 200);
  assert.equal(parsed[0].carts, 30);
  // Weighted position: (3.5*800 + 1.5*200) / 1000 = (2800 + 300) / 1000 = 3.1
  assert.ok(Math.abs(parsed[0].position - 3.1) < 1e-6);
});

test("parseOzonFunnel parses Wildberries funnel report", () => {
  const rows = [
    ["Отчёт по воронке Wildberries"],
    [
      "Артикул WB",
      "Артикул продавца",
      "Название",
      "Дата",
      "Переходы в карточку",
      "Положили в корзину",
      "Схема работы",
    ],
    ["98765432", "WB-OFFER-1", "Тестовый товар WB", "25.10.2026", 300, 45, "FBW"],
    ["98765432", "WB-OFFER-1", "Тестовый товар WB", "25.10.2026", 100, 15, "FBW"],
  ];

  const parsed = parseOzonFunnel(rows, "wb");
  assert.equal(parsed.length, 1);
  assert.equal(parsed[0].sku, "98765432");
  assert.equal(parsed[0].day, "2026-10-25");
  assert.equal(parsed[0].offer_id, "WB-OFFER-1");
  assert.equal(parsed[0].title, "Тестовый товар WB");
  assert.equal(parsed[0].clicks, 400);
  assert.equal(parsed[0].carts, 60);
  assert.equal(parsed[0].impressions, 400); // defaults to clicks when no views column
});

test("parseOzonFunnel parses Yandex Market funnel report with alphanumeric SKU", () => {
  const rows = [
    [
      "Ваш SKU",
      "Название товара",
      "День",
      "Показы",
      "Клики",
      "Добавления в корзину",
      "Модель работы",
    ],
    ["YM.SKU-001:X", "Кофеварка YM", "2026-10-25", 5000, 250, 30, "FBY"],
  ];

  const parsed = parseOzonFunnel(rows, "ym");
  assert.equal(parsed.length, 1);
  assert.equal(parsed[0].sku, "YM.SKU-001:X");
  assert.equal(parsed[0].offer_id, "YM.SKU-001:X");
  assert.equal(parsed[0].day, "2026-10-25");
  assert.equal(parsed[0].impressions, 5000);
  assert.equal(parsed[0].clicks, 250);
  assert.equal(parsed[0].carts, 30);
});
