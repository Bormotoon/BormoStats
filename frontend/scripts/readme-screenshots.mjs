// Screenshots for the README, taken from the production build with every API call mocked.
//
// The data is a fictional shop generated below: no stack, database or marketplace key is
// involved, and any request that is not to the local preview server (or Google Fonts) is
// aborted, so a screenshot can never show real data.
//
//   cd frontend && npm run build && npm run screenshots
//
// Writes docs/screenshots/{ru,en}/<page>.png at the repository root.

import { spawn } from "node:child_process";
import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const PORT = 4179;
const ORIGIN = `http://127.0.0.1:${PORT}`;
const IMG_HOST = "https://demo-images.bormostats.invalid";
const DAY_MS = 86_400_000;

const PAGES = [
  { id: "dashboard", height: 1340 },
  { id: "sales" },
  { id: "finance", height: 1000 },
  { id: "stocks" },
  { id: "funnel" },
  { id: "ads" },
  { id: "reviews", height: 1000 },
  { id: "pricing" },
  { id: "bidder" },
  { id: "pnl" },
  { id: "abcXyz" },
  { id: "kpis" },
  { id: "system", height: 620 },
];

// ---------------------------------------------------------------- the fictional shop

let seed = 20261018;
function rnd() {
  seed = (seed * 1664525 + 1013904223) % 4294967296;
  return seed / 4294967296;
}
const round = (v, d = 2) => Math.round(v * 10 ** d) / 10 ** d;

const PRODUCTS = [
  { slug: "plaid", offer: "UD-PLAID-150", title: "Плед флисовый 150×200, графит", price: 1890, cost: 640, base: 22, hue: 220, icon: "🛋️" },
  { slug: "mug", offer: "UD-MUG-350", title: "Кружка керамическая 350 мл, матовая", price: 690, cost: 180, base: 38, hue: 28, icon: "☕" },
  { slug: "candle", offer: "UD-CANDLE-LAV", title: "Свеча ароматическая «Лаванда», 200 г", price: 990, cost: 260, base: 27, hue: 270, icon: "🕯️" },
  { slug: "pillow", offer: "UD-PILLOW-45", title: "Подушка декоративная 45×45, велюр", price: 1290, cost: 410, base: 16, hue: 340, icon: "🛏️" },
  { slug: "towels", offer: "UD-TOWEL-SET3", title: "Набор полотенец, 3 шт, хлопок", price: 2490, cost: 980, base: 11, hue: 190, icon: "🧺" },
  { slug: "lamp", offer: "UD-LAMP-MOON", title: "Ночник LED «Луна», 15 см", price: 1590, cost: 520, base: 13, hue: 48, icon: "🌙" },
  { slug: "organizer", offer: "UD-ORG-COSM", title: "Органайзер для косметики, акрил", price: 1190, cost: 350, base: 9, hue: 160, icon: "💄" },
  { slug: "rug", offer: "UD-RUG-BATH", title: "Коврик для ванной 50×80, хлопок", price: 1390, cost: 470, base: 7, hue: 120, icon: "🛁" },
].map((p, i) => ({ ...p, wbId: 2_100_000 + i * 17, ozonId: 9_400_000 + i * 23, image: `${IMG_HOST}/${p.slug}.svg` }));

const MARKETPLACES = [
  { id: "wb", share: 0.62, payoutRate: 0.71, warehouses: ["Коледино", "Электросталь", "Казань"] },
  { id: "ozon", share: 0.38, payoutRate: 0.68, warehouses: ["Хоругвино", "Пушкино", "Екатеринбург"] },
];
const productId = (p, mp) => String(mp === "wb" ? p.wbId : p.ozonId);

function productImage(p) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="180" height="240" viewBox="0 0 180 240">
  <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="hsl(${p.hue},70%,88%)"/><stop offset="1" stop-color="hsl(${p.hue},55%,72%)"/>
  </linearGradient></defs>
  <rect width="180" height="240" fill="url(#g)"/>
  <circle cx="90" cy="112" r="58" fill="white" fill-opacity="0.45"/>
  <text x="90" y="134" font-size="64" text-anchor="middle">${p.icon}</text>
  <rect x="24" y="196" width="132" height="10" rx="5" fill="white" fill-opacity="0.6"/>
</svg>`;
}

function days(from, to) {
  const out = [];
  for (let t = Date.parse(from); t <= Date.parse(to); t += DAY_MS) out.push(new Date(t).toISOString().slice(0, 10));
  return out;
}
const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n) => new Date(Date.now() - n * DAY_MS).toISOString().slice(0, 10);

// demand of a product on a day: weekly rhythm, a gentle growth trend and noise
function demand(p, day, mp) {
  const date = new Date(day);
  const weekday = date.getUTCDay();
  const weekly = weekday === 0 || weekday === 6 ? 1.25 : weekday === 1 ? 0.85 : 1;
  const trend = 1 + (Date.parse(day) - Date.now()) / (DAY_MS * 120);
  return Math.max(0, Math.round(p.base * mp.share * weekly * trend * (0.75 + rnd() * 0.5)));
}

function salesRows(from, to) {
  const rows = [];
  for (const day of days(from, to)) {
    for (const mp of MARKETPLACES) {
      for (const p of PRODUCTS) {
        const qty = demand(p, day, mp);
        if (!qty) continue;
        const price = p.price * (mp.id === "ozon" ? 1.04 : 1);
        const returns = rnd() < 0.12 ? 1 : 0;
        rows.push({
          day, marketplace: mp.id, account_id: "default", product_id: productId(p, mp.id),
          title: p.title, offer_id: p.offer, image_url: p.image,
          qty, revenue: round(qty * price), returns_qty: returns, payout: round(qty * price * mp.payoutRate),
        });
      }
    }
  }
  return rows;
}

function funnelRows(from, to) {
  const rows = [];
  for (const day of days(from, to)) {
    for (const mp of MARKETPLACES) {
      for (const p of PRODUCTS) {
        const orders = demand(p, day, mp) + 1;
        const views = Math.round(orders * (28 + rnd() * 22));
        const carts = Math.round(orders * (2.4 + rnd() * 1.2));
        rows.push({
          day, marketplace: mp.id, account_id: "default", product_id: productId(p, mp.id),
          title: p.title, offer_id: p.offer, image_url: p.image,
          views, adds_to_cart: carts, orders, cr_order: orders / views, cr_cart: carts / views,
        });
      }
    }
  }
  return rows;
}

const CAMPAIGNS = [
  { id: "WB-31207", mp: "wb", title: "Пледы — поиск", spend: 1900 },
  { id: "WB-31244", mp: "wb", title: "Кружки и свечи — каталог", spend: 1150 },
  { id: "OZ-8803", mp: "ozon", title: "Трафареты: текстиль", spend: 980 },
  { id: "OZ-8817", mp: "ozon", title: "Продвижение в поиске: декор", spend: 640 },
];

function adsRows(from, to) {
  const rows = [];
  for (const day of days(from, to)) {
    for (const c of CAMPAIGNS) {
      const cost = round(c.spend * (0.7 + rnd() * 0.6));
      const impressions = Math.round(cost * (2.4 + rnd() * 0.8));
      const clicks = Math.round(impressions * (0.022 + rnd() * 0.012));
      const orders = Math.max(1, Math.round(clicks * (0.045 + rnd() * 0.03)));
      const revenue = round(orders * (1100 + rnd() * 700));
      rows.push({
        day, marketplace: c.mp, account_id: "default", campaign_id: c.id,
        impressions, clicks, cost, orders, revenue, acos: cost / revenue, romi: (revenue - cost) / cost,
      });
    }
  }
  return rows;
}

function stockRows() {
  const rows = [];
  PRODUCTS.forEach((p, i) => {
    for (const mp of MARKETPLACES) {
      mp.warehouses.forEach((warehouse, w) => {
        // two products run low, so the low-stock highlight shows up
        const low = (p.slug === "rug" && mp.id === "wb") || (p.slug === "organizer" && mp.id === "ozon");
        const units = low ? (w === 0 ? 2 : 0) : Math.round(p.base * (6 - w * 1.7) * (0.7 + rnd() * 0.6) + i);
        rows.push({
          day: today(), marketplace: mp.id, account_id: "default", product_id: productId(p, mp.id),
          warehouse_id: 500 + w, warehouse_name: warehouse, title: p.title, offer_id: p.offer, image_url: p.image, stock_end: units,
        });
      });
    }
  });
  return rows;
}

function financeRows(from, to) {
  const rows = [];
  const balance = { wb: 186_400, ozon: 94_300 };
  days(from, to).forEach((day, i) => {
    for (const mp of MARKETPLACES) {
      const sales = round(PRODUCTS.reduce((s, p) => s + p.base * p.price * mp.share, 0) * (0.8 + rnd() * 0.4));
      const parts = {
        sales,
        returns: round(-sales * (0.02 + rnd() * 0.02)),
        commission: round(-sales * (mp.id === "wb" ? 0.205 : 0.19)),
        acquiring: round(-sales * 0.015),
        logistics: round(-sales * 0.07),
        reverse_logistics: round(-sales * 0.004),
        storage: round(-sales * 0.012),
        acceptance: i % 7 === 2 ? round(-1200 - rnd() * 800) : 0,
        penalties: i === 11 && mp.id === "wb" ? -500 : 0,
        other: round(-sales * 0.003),
      };
      const net = round(Object.values(parts).reduce((s, v) => s + v, 0));
      const payouts = mp.id === "ozon" ? (i % 14 === 6 ? round(-balance.ozon * 0.9) : 0) : null;
      const opening = balance[mp.id];
      balance[mp.id] = round(opening + net + (payouts || 0));
      rows.push({
        day, marketplace: mp.id, account_id: "default", ...parts, net_accrued: net, payouts,
        opening_balance: mp.id === "ozon" ? opening : null,
        closing_balance: mp.id === "ozon" ? balance[mp.id] : null,
        for_withdraw: null, details: "",
      });
    }
  });
  return rows;
}

const BALANCE = [
  { marketplace: "ozon", account_id: "default", balance: 118_640.5, for_withdraw: null, as_of: new Date(Date.now() - 20 * 60_000).toISOString(), last_payout_day: daysAgo(4) },
  { marketplace: "wb", account_id: "default", balance: 243_910, for_withdraw: 201_480, as_of: new Date(Date.now() - 20 * 60_000).toISOString(), last_payout_day: null },
];

function kpis() {
  return MARKETPLACES.map((mp) => {
    const revenue = PRODUCTS.reduce((s, p) => s + p.base * p.price * mp.share * 30, 0);
    const cost = CAMPAIGNS.filter((c) => c.mp === mp.id).reduce((s, c) => s + c.spend * 30, 0);
    return {
      marketplace: mp.id, account_id: "default", revenue_30d: round(revenue), qty_30d: Math.round(revenue / 1200),
      returns_30d: Math.round(revenue / 1200 * 0.04), cost_30d: cost, acos_30d: cost / revenue,
    };
  });
}

const TASKS = [
  { task_id: "t1", trigger_type: "turnover", priority: "high", title: "Коврик для ванной заканчивается на WB", description: "Осталось 2 шт на складах WB при продажах ~4 шт/день: запаса меньше чем на сутки. Отгрузите поставку на Коледино." },
  { task_id: "t2", trigger_type: "bad_ad", priority: "high", title: "Кампания OZ-8817: ДРР 31% за 7 дней", description: "Расходы растут быстрее заказов. Снизьте ставку или исключите нерелевантные запросы." },
  { task_id: "t3", trigger_type: "stagnant", priority: "medium", title: "Набор полотенец лежит на складе Казань", description: "Нет продаж со склада 21 день при остатке 38 шт. Рассмотрите перераспределение или акцию." },
];

function abcXyz() {
  const classes = [["A", "X"], ["A", "Y"], ["A", "X"], ["B", "X"], ["B", "Z"], ["B", "Y"], ["C", "Y"], ["C", "Z"]];
  const total = PRODUCTS.reduce((s, p) => s + p.base * p.price, 0);
  return PRODUCTS.flatMap((p, i) => MARKETPLACES.map((mp) => ({
    marketplace: mp.id, account_id: "default", product_id: productId(p, mp.id),
    revenue_60d: round(p.base * p.price * mp.share * 60),
    share_pct: (p.base * p.price) / total * mp.share,
    abc_class: classes[i][0], xyz_class: classes[i][1],
    cv_pct: { X: 7 + i, Y: 14 + i, Z: 31 + i * 2 }[classes[i][1]],
    daily_mean_qty: p.base * mp.share,
  }))).sort((a, b) => b.revenue_60d - a.revenue_60d);
}

function pnl() {
  const rows = [];
  for (let m = 5; m >= 0; m--) {
    const d = new Date();
    d.setUTCDate(1);
    d.setUTCMonth(d.getUTCMonth() - m);
    const month = d.toISOString().slice(0, 7);
    for (const mp of MARKETPLACES) {
      const revenue = round(PRODUCTS.reduce((s, p) => s + p.base * p.price, 0) * mp.share * 30 * (0.8 + (5 - m) * 0.05));
      const commission = round(revenue * 0.2), logistics = round(revenue * 0.07), returns = round(revenue * 0.03);
      const storage = round(revenue * 0.012), other = round(revenue * 0.01), cogs = round(revenue * 0.33);
      const ads = round(revenue * 0.08), extra = mp.id === "wb" ? 42_000 : 26_000;
      const gross = revenue - commission - logistics - returns - storage - other - cogs;
      const operating = gross - ads - extra;
      rows.push({
        month, organization_id: "demo", marketplace: mp.id, account_id: "default",
        revenue_rub: revenue, commission_rub: commission, logistics_rub: logistics, returns_cost_rub: returns,
        storage_rub: storage, other_costs_rub: other, net_accrued_rub: round(revenue - commission - logistics - returns - storage - other),
        cogs_rub: cogs, gross_profit_rub: round(gross), ad_cost_rub: ads, additional_expenses_rub: extra,
        operating_profit_rub: round(operating), ebitda_rub: round(operating), net_profit_rub: round(operating * 0.94),
        margin_pct: round((gross / revenue) * 100),
      });
    }
  }
  return rows.reverse();
}

const EXPENSES = [
  { expense_id: "e1", category: "Аренда склада", amount_rub: 38_000, month: daysAgo(0).slice(0, 7) },
  { expense_id: "e2", category: "Фулфилмент", amount_rub: 21_500, month: daysAgo(0).slice(0, 7) },
  { expense_id: "e3", category: "Фотосъёмка карточек", amount_rub: 8_500, month: daysAgo(0).slice(0, 7) },
  { expense_id: "e4", category: "Бухгалтерия", amount_rub: 6_000, month: daysAgo(31).slice(0, 7) },
];

function pricing() {
  return PRODUCTS.flatMap((p, i) => MARKETPLACES.map((mp) => {
    const list = Math.round(p.price * 1.6 / 10) * 10;
    const discount = 35 + (i % 3) * 3;
    const seller = round(list * (1 - discount / 100));
    const mpDiscount = mp.id === "wb" ? 12 + (i % 4) : 6 + (i % 3);
    const commissionPct = mp.id === "wb" ? 20.5 : 19;
    const commission = round(seller * commissionPct / 100);
    const acquiring = round(seller * 0.015);
    const logistics = 74 + i * 6;
    const fees = round(commission + acquiring + logistics);
    const margin = round(seller - fees - p.cost);
    const hasRule = i < 5;
    return {
      marketplace: mp.id, account_id: "default", offer_id: p.offer, product_id: productId(p, mp.id),
      title: p.title, image_url: p.image, list_price: list, seller_discount_pct: discount, seller_price: seller,
      mp_discount_pct: mpDiscount, mp_discount_scope: "product", mp_discount_samples: 12 + i,
      buyer_price: round(seller * (1 - mpDiscount / 100)), commission_pct: commissionPct, commission_rub: commission,
      acquiring_rub: acquiring, logistics_rub: logistics, fees_rub: fees, cost_price: p.cost,
      margin_rub: margin, margin_pct: round((margin / seller) * 100),
      breakeven_price: round((p.cost + acquiring + logistics) / (1 - commissionPct / 100)), min_price: null,
      auto_actions_enabled: true, price_seen_at: new Date(Date.now() - 3_600_000).toISOString(),
      rule_id: hasRule ? `r-${mp.id}-${i}` : null, mode: hasRule ? "buyer_price" : null,
      target_price: hasRule ? Math.round(seller * (1 - mpDiscount / 100) / 10) * 10 : null,
      rule_is_active: hasRule ? true : null, rule_dry_run: hasRule ? i % 2 === 1 : null, target_gap_pct: hasRule ? round(rnd() * 0.8, 2) : null,
    };
  }));
}

function compare() {
  return pricing().filter((r) => r.marketplace === "wb").map((wb, i) => {
    const ozonBuyer = round(wb.buyer_price * (1.02 + (i % 3) * 0.03));
    return {
      offer_id: wb.offer_id, title: wb.title, image_url: wb.image_url,
      wb_seller_price: wb.seller_price, wb_buyer_price: wb.buyer_price,
      ozon_seller_price: round(ozonBuyer * 1.08), ozon_buyer_price: ozonBuyer,
      buyer_spread_pct: round(((ozonBuyer - wb.buyer_price) / wb.buyer_price) * 100),
    };
  });
}

const REVIEWS = [
  { review_id: "rv1", marketplace: "wb", rating: 5, p: 0, user_name: "Анна", photos: 2, text: "Очень мягкий и тёплый плед, цвет как на фото. Брала в подарок маме — она в восторге!", pros: "Мягкий, не линяет после стирки", cons: "" },
  { review_id: "rv2", marketplace: "ozon", rating: 3, p: 1, user_name: "Игорь", photos: 0, text: "Кружка красивая, но пришла в слабой упаковке, на ручке небольшой скол.", pros: "Приятная матовая глазурь", cons: "Упаковка" },
  { review_id: "rv3", marketplace: "wb", rating: 5, p: 2, user_name: "Мария", photos: 1, text: "Запах лаванды ненавязчивый, горит ровно, без копоти. Закажу ещё.", pros: "", cons: "" },
  { review_id: "rv4", marketplace: "wb", rating: 4, p: 5, user_name: "Дмитрий", photos: 0, text: "Ночник хороший, но хотелось бы регулировку яркости поплавнее.", pros: "Красиво светится", cons: "Яркость меняется ступенями" },
].map((r, i) => {
  const p = PRODUCTS[r.p];
  return {
    ...r, product_id: productId(p, r.marketplace), product_name: p.title, offer_id: p.offer, image_url: p.image,
    has_text: true, is_answered: false, reply_status: "", reply_source: "", answer_text: "", reply_error: "",
    created_at: new Date(Date.now() - (i + 1) * 5_400_000).toISOString(),
  };
});

function actions(source) {
  return [0, 1, 2, 3].map((i) => ({
    action_id: `${source}-a${i}`, created_at: new Date(Date.now() - (i + 1) * 2_700_000).toISOString(),
    marketplace: i % 2 ? "ozon" : "wb", target_id: source === "bidder" ? CAMPAIGNS[i].id : PRODUCTS[i].offer,
    before_value: source === "bidder" ? 180 + i * 20 : PRODUCTS[i].price + 60, after_value: source === "bidder" ? 165 + i * 20 : PRODUCTS[i].price,
    status: i === 0 ? "applied" : "simulated", response_status: i === 0 ? 200 : null, response_body: "",
  }));
}

function paginated(items, url) {
  const limit = Number(url.searchParams.get("limit") || 1000);
  const offset = Number(url.searchParams.get("offset") || 0);
  const page = items.slice(offset, offset + limit);
  const next = offset + limit < items.length ? offset + limit : null;
  return { items: page, pagination: { limit, offset, returned: page.length, next_offset: next, has_more: next !== null } };
}

const filterMp = (rows, url) => {
  const mp = url.searchParams.get("marketplace");
  return mp ? rows.filter((r) => r.marketplace === mp) : rows;
};
const range = (url) => [url.searchParams.get("date_from") || daysAgo(29), url.searchParams.get("date_to") || today()];

// every response is computed once per path+query so repeated loads stay identical
const cache = new Map();
function answer(url) {
  const path = url.pathname.replace(/^\/+/, "/");
  const key = `${path}?${[...url.searchParams].filter(([k]) => k !== "offset").sort().join("&")}`;
  if (!cache.has(key)) cache.set(key, build(path, url));
  return cache.get(key);
}

function build(path, url) {
  const routes = {
    "/health/live": () => ({ status: "ok" }),
    "/health/ready": () => ({ status: "ready" }),
    "/health/dependencies": () => ({
      status: "ok",
      dependencies: { clickhouse: { status: "ok", latency_ms: 3 }, redis: { status: "ok", latency_ms: 1 }, celery: { status: "ok", latency_ms: 12 } },
    }),
    "/api/v1/users/me": () => ({
      principal_id: "demo", organization_id: "demo", organization_name: "Уютный дом (демо)", role: "owner",
      scopes: ["read:analytics"], auth_method: "admin_key", name: "Demo", email: "demo@example.com", api_key_expires_at: null,
    }),
    "/api/v1/accounts": () => [
      { account_id: "default", marketplace: "wb", organization_id: "demo", title: "Уютный дом — WB" },
      { account_id: "default", marketplace: "ozon", organization_id: "demo", title: "Уютный дом — Ozon" },
    ],
    "/api/v1/freshness": () => ({ marts: [{ name: "mrt_sales_daily", updated_at: new Date(Date.now() - 12 * 60_000).toISOString() }], source_errors_24h: [] }),
    "/api/v1/insights/tasks": () => TASKS,
    "/api/v1/sales/daily": () => paginated(filterMp(salesRows(...range(url)), url), url),
    "/api/v1/funnel/daily": () => paginated(filterMp(funnelRows(...range(url)), url), url),
    "/api/v1/ads/daily": () => paginated(filterMp(adsRows(...range(url)), url), url),
    "/api/v1/stocks/current": () => paginated(filterMp(stockRows(), url), url),
    "/api/v1/finance/daily": () => paginated(filterMp(financeRows(...range(url)), url), url),
    "/api/v1/finance/balance": () => paginated(filterMp(BALANCE, url), url),
    "/api/v1/kpis": () => paginated(filterMp(kpis(), url), url),
    "/api/v1/abc-xyz": () => filterMp(abcXyz(), url),
    "/api/v1/pnl": () => pnl(),
    "/api/v1/pnl/expenses": () => EXPENSES,
    "/api/v1/pricing/breakdown": () => pricing(),
    "/api/v1/pricing/compare": () => compare(),
    "/api/v1/pricing/status": () => ({ marketplace_actions_enabled: true }),
    "/api/v1/bidder/campaigns": () => CAMPAIGNS.map((c, i) => ({
      campaign_id: c.id, marketplace: c.mp, account_id: "default", title: c.title, status: i === 3 ? "paused" : "active",
      daily_budget: c.spend * 1.5, current_cpm: 160 + i * 35, current_cpc: null,
    })),
    "/api/v1/bidder/rules": () => CAMPAIGNS.slice(0, 3).map((c, i) => ({
      rule_id: `b${i}`, campaign_id: c.id, marketplace: c.mp, account_id: "default", target_cpm: 150 + i * 40, max_cpm: 320 + i * 60,
      target_position: [3, 5, 8][i], product_id: String(PRODUCTS[i].wbId), placement: "combined", is_active: true, dry_run: i !== 0,
    })),
    "/api/v1/bidder/actions": () => actions("bidder"),
    "/api/v1/repricer/rules": () => PRODUCTS.slice(0, 3).map((p, i) => ({
      rule_id: `rp${i}`, marketplace: i === 1 ? "ozon" : "wb", account_id: "default", product_id: p.offer, mode: "buyer_price",
      target_price: p.price, max_step_pct: 5, min_price: Math.round(p.price * 0.8), max_price: Math.round(p.price * 1.3),
      target_margin_percent: 25, is_active: true, dry_run: i !== 0,
    })),
    "/api/v1/repricer/breakeven": () => pricing().map((r) => ({
      marketplace: r.marketplace, account_id: r.account_id, offer_id: r.offer_id, product_id: r.product_id, current_price: r.seller_price,
      cost_price: r.cost_price, breakeven_price: r.breakeven_price, commission_pct: r.commission_pct, logistics_rub: r.logistics_rub,
    })),
    "/api/v1/repricer/actions": () => actions("repricer"),
    "/api/v1/reviews/summary": () => ({
      unanswered_with_text: REVIEWS.length, unanswered_without_text: 17, sent_today: 9,
      sync: [
        { marketplace: "wb", status: "ok", synced_at: new Date(Date.now() - 6 * 60_000).toISOString() },
        { marketplace: "ozon", status: "ok", synced_at: new Date(Date.now() - 9 * 60_000).toISOString() },
      ],
    }),
    "/api/v1/reviews": () => ({ items: filterMp(REVIEWS, url), total: filterMp(REVIEWS, url).length }),
    "/api/v1/reviews/settings": () => ({ auto_enabled: false, modes: {} }),
    "/api/v1/reviews/templates": () => [],
  };
  const handler = routes[path];
  return handler ? { status: 200, body: handler() } : { status: 200, body: [] };
}

// ---------------------------------------------------------------- capture

async function waitForServer(url, timeoutMs = 30_000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`preview server did not start at ${url}`);
}

async function shoot(browser, lang) {
  const outDir = resolve(ROOT, "docs", "screenshots", lang);
  await mkdir(outDir, { recursive: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
    locale: lang === "ru" ? "ru-RU" : "en-GB",
    timezoneId: "Europe/Moscow",
  });
  await context.addInitScript((l) => {
    localStorage.setItem("bormostats_api_key", "bsk_demo_readme-screenshots");
    localStorage.setItem("bormostats_ui_lang", l);
  }, lang);

  await context.route("**/*", (route) => {
    const url = new URL(route.request().url());
    if (url.origin === IMG_HOST) {
      const product = PRODUCTS.find((p) => url.pathname === `/${p.slug}.svg`);
      return route.fulfill({ status: 200, contentType: "image/svg+xml", body: product ? productImage(product) : "" });
    }
    if (url.origin === ORIGIN && (url.pathname.startsWith("/api/") || url.pathname.startsWith("/health/"))) {
      const { status, body } = answer(url);
      return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    }
    if (url.origin === ORIGIN || url.hostname === "fonts.googleapis.com" || url.hostname === "fonts.gstatic.com") {
      return route.continue();
    }
    // nothing else may be contacted: the screenshots must show the mock shop only
    return route.abort();
  });

  const page = await context.newPage();
  for (const { id, height = 900 } of PAGES) {
    await page.setViewportSize({ width: 1440, height });
    await page.goto(`${ORIGIN}/ui/#/${id}`);
    await page.waitForLoadState("networkidle");
    await page.evaluate(() => document.fonts.ready);
    // charts animate in
    await page.waitForTimeout(1800);
    await page.screenshot({ path: resolve(outDir, `${id}.png`) });
    console.log(`${lang}/${id}.png`);
  }
  await context.close();
}

const server = spawn("npx", ["vite", "preview", "--host", "127.0.0.1", "--port", String(PORT), "--strictPort"], {
  cwd: resolve(ROOT, "frontend"),
  stdio: "ignore",
});
try {
  await waitForServer(`${ORIGIN}/ui/`);
  const browser = await chromium.launch();
  for (const lang of ["ru", "en"]) await shoot(browser, lang);
  await browser.close();
} finally {
  server.kill();
}
