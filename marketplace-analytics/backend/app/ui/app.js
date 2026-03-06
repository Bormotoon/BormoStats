const PAGE_DEFS = [
  {
    id: "dashboard",
    title: "Dashboard",
    subtitle: "Операционная сводка по продажам, рекламе, остаткам и состоянию сервисов",
    filters: ["dateFrom", "dateTo", "marketplace", "accountId", "limit"],
  },
  {
    id: "sales",
    title: "Sales",
    subtitle: "Дневные продажи по витрине mrt_sales_daily",
    filters: ["dateFrom", "dateTo", "marketplace", "accountId", "limit"],
  },
  {
    id: "stocks",
    title: "Stocks",
    subtitle: "Текущие остатки по последнему дню в mrt_stock_daily",
    filters: ["marketplace", "accountId", "limit"],
  },
  {
    id: "funnel",
    title: "Funnel",
    subtitle: "Воронка карточки: просмотры, корзина, заказы, конверсии",
    filters: ["dateFrom", "dateTo", "marketplace", "accountId", "limit"],
  },
  {
    id: "ads",
    title: "Ads",
    subtitle: "Рекламные метрики: cost, revenue, ACOS, ROMI",
    filters: ["dateFrom", "dateTo", "marketplace", "accountId", "limit"],
  },
  {
    id: "kpis",
    title: "KPIs",
    subtitle: "KPI 30d по marketplace/account",
    filters: ["marketplace", "accountId"],
  },
  {
    id: "watermarks",
    title: "Watermarks",
    subtitle: "Системные водяные знаки ingestion (admin endpoint)",
    filters: [],
  },
  {
    id: "taskRuns",
    title: "Task Runs",
    subtitle: "История запусков задач workers (admin endpoint)",
    filters: ["taskRunsLimit"],
  },
  {
    id: "adminActions",
    title: "Admin Actions",
    subtitle: "Ручной запуск задач и backfill через Admin API",
    filters: [],
  },
  {
    id: "system",
    title: "System",
    subtitle: "Health, readiness и Prometheus metrics",
    filters: [],
  },
];

const STORE_KEYS = {
  apiBase: "bormostats_ui_api_base",
  adminKey: "bormostats_ui_admin_key",
  theme: "bormostats_ui_theme",
};

const state = {
  page: "dashboard",
  apiBase: "",
  adminKey: "",
  filters: {
    dateFrom: isoDay(-30),
    dateTo: isoDay(0),
    marketplace: "",
    accountId: "",
    limit: "1000",
    taskRunsLimit: "200",
  },
};

const refs = {
  appShell: document.getElementById("app-shell"),
  navList: document.getElementById("nav-list"),
  pageTitle: document.getElementById("page-title"),
  pageSubtitle: document.getElementById("page-subtitle"),
  filters: document.getElementById("filters"),
  feedback: document.getElementById("feedback"),
  pageContent: document.getElementById("page-content"),
  menuToggle: document.getElementById("menu-toggle"),
  reloadButton: document.getElementById("reload-button"),
  themeToggle: document.getElementById("theme-toggle"),
  apiBaseInput: document.getElementById("api-base-input"),
  adminKeyInput: document.getElementById("admin-key-input"),
  saveSettingsButton: document.getElementById("save-settings-button"),
};

function isoDay(offsetDays) {
  const now = new Date();
  now.setUTCDate(now.getUTCDate() + offsetDays);
  return now.toISOString().slice(0, 10);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function normalizeBaseUrl(value) {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }
  return trimmed.replace(/\/+$/, "");
}

function toApiUrl(path, query = null) {
  const hasBase = Boolean(state.apiBase);
  const url = new URL(
    `${hasBase ? state.apiBase : window.location.origin}${path}`,
    window.location.origin,
  );
  if (query) {
    Object.entries(query).forEach(([key, value]) => {
      if (value === "" || value === null || value === undefined) {
        return;
      }
      url.searchParams.set(key, String(value));
    });
  }
  return url.toString();
}

async function request(path, options = {}) {
  const { query, method = "GET", body, admin = false, expectText = false } = options;
  const headers = {};
  if (admin) {
    if (!state.adminKey.trim()) {
      throw new Error("Admin API key не задан. Укажите ключ в Settings.");
    }
    headers["X-API-Key"] = state.adminKey.trim();
  }
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(toApiUrl(path, query), {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`HTTP ${response.status} ${response.statusText}: ${text}`);
  }

  if (expectText) {
    return response.text();
  }
  return response.json();
}

async function safeCall(factory) {
  try {
    const data = await factory();
    return { ok: true, data, error: "" };
  } catch (error) {
    return {
      ok: false,
      data: null,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

function setFeedback(message, kind = "success") {
  if (!message) {
    refs.feedback.className = "feedback hidden";
    refs.feedback.textContent = "";
    return;
  }
  refs.feedback.className = `feedback ${kind}`;
  refs.feedback.textContent = message;
}

function parseHash() {
  const raw = window.location.hash.replace("#", "");
  const page = PAGE_DEFS.find((item) => item.id === raw)?.id || "dashboard";
  state.page = page;
}

function setHash(pageId) {
  window.location.hash = `#${pageId}`;
}

function activePageDef() {
  return PAGE_DEFS.find((page) => page.id === state.page) || PAGE_DEFS[0];
}

function sum(rows, key) {
  return rows.reduce((acc, row) => acc + Number(row[key] || 0), 0);
}

function avg(rows, key) {
  if (!rows.length) {
    return 0;
  }
  return sum(rows, key) / rows.length;
}

function groupSeries(rows, byKey, valueKey) {
  const grouped = new Map();
  for (const row of rows) {
    const label = String(row[byKey] || "");
    grouped.set(label, (grouped.get(label) || 0) + Number(row[valueKey] || 0));
  }
  return [...grouped.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([label, value]) => ({ label, value }));
}

function numberFmt(value, digits = 0) {
  const num = Number(value || 0);
  return num.toLocaleString("ru-RU", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function moneyFmt(value) {
  const num = Number(value || 0);
  return num.toLocaleString("ru-RU", {
    style: "currency",
    currency: "RUB",
    maximumFractionDigits: 2,
  });
}

function formatCell(key, value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  const keyLower = key.toLowerCase();
  if (typeof value === "number") {
    if (["revenue", "cost", "payout", "amount", "orders_sum"].some((token) => keyLower.includes(token))) {
      return moneyFmt(value);
    }
    if (["acos", "romi", "cr_"].some((token) => keyLower.includes(token))) {
      return `${numberFmt(value * 100, 2)}%`;
    }
    if (Number.isInteger(value)) {
      return numberFmt(value, 0);
    }
    return numberFmt(value, 2);
  }
  if (typeof value === "string" && keyLower.includes("meta_json")) {
    const trimmed = value.length > 240 ? `${value.slice(0, 240)}...` : value;
    return `<span class="mono">${escapeHtml(trimmed)}</span>`;
  }
  return escapeHtml(value);
}

function tableHtml(rows, preferredColumns = []) {
  if (!rows.length) {
    return '<div class="empty-state">Данных пока нет</div>';
  }
  const columns = preferredColumns.length
    ? preferredColumns.filter((col) => rows.some((row) => Object.prototype.hasOwnProperty.call(row, col)))
    : Object.keys(rows[0]);
  const headers = columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("");
  const body = rows
    .map((row) => {
      const cells = columns.map((column) => `<td>${formatCell(column, row[column])}</td>`).join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");

  return `<div class="table-wrap"><table><thead><tr>${headers}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function metricCard(label, value, subvalue = "") {
  return `
    <article class="metric-card">
      <div class="metric-label">${escapeHtml(label)}</div>
      <div class="metric-value">${value}</div>
      ${subvalue ? `<div class="metric-subvalue">${escapeHtml(subvalue)}</div>` : ""}
    </article>
  `;
}

function chartHtml(title, series, stroke = "var(--md-sys-color-primary)") {
  if (!series.length) {
    return `
      <section class="chart">
        <h3 class="chart-title">${escapeHtml(title)}</h3>
        <div class="empty-state">Нет данных для графика</div>
      </section>
    `;
  }

  const width = 760;
  const height = 220;
  const padding = 24;
  const values = series.map((item) => Number(item.value || 0));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const stepX = (width - padding * 2) / Math.max(1, series.length - 1);

  const points = series.map((item, index) => {
    const x = padding + index * stepX;
    const y = height - padding - ((Number(item.value || 0) - min) / range) * (height - padding * 2);
    return { x, y, label: item.label, value: item.value };
  });

  const polyline = points.map((point) => `${point.x},${point.y}`).join(" ");
  const dots = points
    .map(
      (point) =>
        `<circle cx="${point.x}" cy="${point.y}" r="3.5" fill="${stroke}">
          <title>${escapeHtml(point.label)}: ${escapeHtml(numberFmt(point.value, 2))}</title>
        </circle>`,
    )
    .join("");

  const xLabels = series
    .filter((_, index) => index % Math.ceil(series.length / 8) === 0 || index === series.length - 1)
    .map(
      (item, index) =>
        `<span>${escapeHtml(item.label)}${index < series.length - 1 ? "" : ""}</span>`,
    )
    .join("");

  return `
    <section class="chart">
      <h3 class="chart-title">${escapeHtml(title)}</h3>
      <svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-label="${escapeHtml(title)}">
        <polyline fill="none" stroke="${stroke}" stroke-width="3.2" points="${polyline}" />
        ${dots}
      </svg>
      <div style="display:flex;justify-content:space-between;gap:8px;color:var(--md-sys-color-on-surface-variant);font-size:0.75rem;flex-wrap:wrap;">
        ${xLabels}
      </div>
    </section>
  `;
}

function statusChip(ok, okText = "OK", failText = "FAIL") {
  return `<span class="status-chip ${ok ? "ok" : "fail"}">${ok ? okText : failText}</span>`;
}

function rawPanel(title, payload) {
  return `
    <section class="panel">
      <h3>${escapeHtml(title)}</h3>
      <pre class="mono">${escapeHtml(JSON.stringify(payload, null, 2))}</pre>
    </section>
  `;
}

function commonParams(includeDates = true) {
  const params = {
    marketplace: state.filters.marketplace,
    account_id: state.filters.accountId,
    limit: Number(state.filters.limit || 1000),
  };
  if (!includeDates) {
    return params;
  }
  return {
    ...params,
    date_from: state.filters.dateFrom,
    date_to: state.filters.dateTo,
  };
}

function renderFilters(pageDef) {
  if (!pageDef.filters.length) {
    refs.filters.innerHTML = "";
    return;
  }

  const fieldTemplate = {
    dateFrom: `
      <label class="field">
        <span>Date From</span>
        <input data-filter="dateFrom" type="date" value="${escapeHtml(state.filters.dateFrom)}" />
      </label>
    `,
    dateTo: `
      <label class="field">
        <span>Date To</span>
        <input data-filter="dateTo" type="date" value="${escapeHtml(state.filters.dateTo)}" />
      </label>
    `,
    marketplace: `
      <label class="field">
        <span>Marketplace</span>
        <select data-filter="marketplace">
          <option value="" ${state.filters.marketplace === "" ? "selected" : ""}>All</option>
          <option value="wb" ${state.filters.marketplace === "wb" ? "selected" : ""}>WB</option>
          <option value="ozon" ${state.filters.marketplace === "ozon" ? "selected" : ""}>Ozon</option>
        </select>
      </label>
    `,
    accountId: `
      <label class="field">
        <span>Account ID</span>
        <input data-filter="accountId" type="text" value="${escapeHtml(state.filters.accountId)}" placeholder="default" />
      </label>
    `,
    limit: `
      <label class="field">
        <span>Limit</span>
        <input data-filter="limit" type="number" min="1" max="10000" value="${escapeHtml(state.filters.limit)}" />
      </label>
    `,
    taskRunsLimit: `
      <label class="field">
        <span>Task Runs Limit</span>
        <input data-filter="taskRunsLimit" type="number" min="1" max="2000" value="${escapeHtml(state.filters.taskRunsLimit)}" />
      </label>
    `,
  };

  const fields = pageDef.filters.map((filterId) => fieldTemplate[filterId]).join("");
  refs.filters.innerHTML = `
    <div class="panel">
      ${fields}
      <button id="apply-filters-button" class="button button-primary" type="button">Apply</button>
      <button id="reset-filters-button" class="button button-outline" type="button">Reset</button>
    </div>
  `;

  document.getElementById("apply-filters-button")?.addEventListener("click", () => {
    document.querySelectorAll("[data-filter]").forEach((element) => {
      const key = element.getAttribute("data-filter");
      if (!key) {
        return;
      }
      state.filters[key] = element.value;
    });
    loadPage();
  });

  document.getElementById("reset-filters-button")?.addEventListener("click", () => {
    state.filters.dateFrom = isoDay(-30);
    state.filters.dateTo = isoDay(0);
    state.filters.marketplace = "";
    state.filters.accountId = "";
    state.filters.limit = "1000";
    state.filters.taskRunsLimit = "200";
    renderFilters(pageDef);
    loadPage();
  });
}

function renderNav() {
  refs.navList.innerHTML = PAGE_DEFS.map(
    (page) => `
      <button class="nav-link ${page.id === state.page ? "active" : ""}" data-page="${page.id}" type="button">
        ${escapeHtml(page.title)}
      </button>
    `,
  ).join("");

  refs.navList.querySelectorAll(".nav-link").forEach((button) => {
    button.addEventListener("click", () => {
      const pageId = button.getAttribute("data-page");
      if (!pageId) {
        return;
      }
      setHash(pageId);
      refs.appShell.classList.remove("nav-open");
    });
  });
}

async function renderDashboard() {
  const sales = await safeCall(() => request("/api/v1/sales/daily", { query: commonParams(true) }));
  const ads = await safeCall(() => request("/api/v1/ads/daily", { query: commonParams(true) }));
  const stocks = await safeCall(() => request("/api/v1/stocks/current", { query: commonParams(false) }));
  const kpis = await safeCall(() => request("/api/v1/kpis", { query: commonParams(false) }));
  const health = await safeCall(() => request("/health"));
  const ready = await safeCall(() => request("/ready"));

  const salesRows = sales.data?.items || [];
  const adsRows = ads.data?.items || [];
  const stockRows = stocks.data?.items || [];
  const kpiRows = kpis.data?.items || [];
  const topProducts = [...salesRows].sort((a, b) => Number(b.revenue || 0) - Number(a.revenue || 0)).slice(0, 10);

  const revenue14 = sum(salesRows, "revenue");
  const qty14 = sum(salesRows, "qty");
  const adCost14 = sum(adsRows, "cost");
  const stockUnits = sum(stockRows, "stock_end");

  const salesSeries = groupSeries(salesRows, "day", "revenue");
  const adsSeries = groupSeries(adsRows, "day", "cost");

  const errors = [sales, ads, stocks, kpis, health, ready].filter((item) => !item.ok).map((item) => item.error);
  if (errors.length) {
    setFeedback(`Часть данных не загрузилась: ${errors.join(" | ")}`, "error");
  }

  return `
    <section class="cards">
      ${metricCard("Service Health", health.ok ? statusChip(true, "Healthy") : statusChip(false), health.ok ? "FastAPI reachable" : "check /health")}
      ${metricCard("Service Readiness", ready.ok ? statusChip(true, "Ready") : statusChip(false), ready.ok ? "ClickHouse + Redis OK" : "check /ready")}
      ${metricCard("Revenue", moneyFmt(revenue14), `за период ${escapeHtml(state.filters.dateFrom)}..${escapeHtml(state.filters.dateTo)}`)}
      ${metricCard("Sales Qty", numberFmt(qty14), "сумма qty по ответу /sales/daily")}
      ${metricCard("Ad Cost", moneyFmt(adCost14), "сумма cost по /ads/daily")}
      ${metricCard("Stock Units", numberFmt(stockUnits), `${numberFmt(stockRows.length)} stock rows`)}
      ${metricCard("KPI Rows", numberFmt(kpiRows.length), "из /kpis")}
    </section>

    <section class="grid-2">
      ${chartHtml("Revenue Trend", salesSeries)}
      ${chartHtml("Ad Spend Trend", adsSeries, "var(--md-sys-color-warning)")}
    </section>

    <section class="panel">
      <h3>Top Products by Revenue</h3>
      ${tableHtml(topProducts, ["day", "marketplace", "account_id", "product_id", "qty", "revenue", "returns_qty", "payout"])}
    </section>
  `;
}

async function renderSales() {
  const result = await request("/api/v1/sales/daily", { query: commonParams(true) });
  const rows = result.items || [];
  return `
    <section class="cards">
      ${metricCard("Rows", numberFmt(rows.length))}
      ${metricCard("Revenue", moneyFmt(sum(rows, "revenue")))}
      ${metricCard("Qty", numberFmt(sum(rows, "qty")))}
      ${metricCard("Returns", numberFmt(sum(rows, "returns_qty")))}
      ${metricCard("Payout", moneyFmt(sum(rows, "payout")))}
    </section>
    ${chartHtml("Revenue by Day", groupSeries(rows, "day", "revenue"))}
    <section class="panel">
      <h3>Sales Daily</h3>
      ${tableHtml(rows, ["day", "marketplace", "account_id", "product_id", "qty", "revenue", "returns_qty", "payout"])}
    </section>
    ${rawPanel("Raw /api/v1/sales/daily", result)}
  `;
}

async function renderStocks() {
  const result = await request("/api/v1/stocks/current", { query: commonParams(false) });
  const rows = result.items || [];
  const lowStock = rows.filter((row) => Number(row.stock_end || 0) <= 5).length;
  return `
    <section class="cards">
      ${metricCard("Rows", numberFmt(rows.length))}
      ${metricCard("Total Stock", numberFmt(sum(rows, "stock_end")))}
      ${metricCard("Low Stock (<=5)", numberFmt(lowStock))}
    </section>
    <section class="panel">
      <h3>Current Stocks</h3>
      ${tableHtml(rows, ["day", "marketplace", "account_id", "product_id", "warehouse_id", "stock_end"])}
    </section>
    ${rawPanel("Raw /api/v1/stocks/current", result)}
  `;
}

async function renderFunnel() {
  const result = await request("/api/v1/funnel/daily", { query: commonParams(true) });
  const rows = result.items || [];
  return `
    <section class="cards">
      ${metricCard("Rows", numberFmt(rows.length))}
      ${metricCard("Views", numberFmt(sum(rows, "views")))}
      ${metricCard("Adds to Cart", numberFmt(sum(rows, "adds_to_cart")))}
      ${metricCard("Orders", numberFmt(sum(rows, "orders")))}
      ${metricCard("Avg CR Order", `${numberFmt(avg(rows, "cr_order") * 100, 2)}%`)}
      ${metricCard("Avg CR Cart", `${numberFmt(avg(rows, "cr_cart") * 100, 2)}%`)}
    </section>
    ${chartHtml("Orders by Day", groupSeries(rows, "day", "orders"))}
    <section class="panel">
      <h3>Funnel Daily</h3>
      ${tableHtml(rows, ["day", "marketplace", "account_id", "product_id", "views", "adds_to_cart", "orders", "cr_order", "cr_cart"])}
    </section>
    ${rawPanel("Raw /api/v1/funnel/daily", result)}
  `;
}

async function renderAds() {
  const result = await request("/api/v1/ads/daily", { query: commonParams(true) });
  const rows = result.items || [];
  return `
    <section class="cards">
      ${metricCard("Rows", numberFmt(rows.length))}
      ${metricCard("Cost", moneyFmt(sum(rows, "cost")))}
      ${metricCard("Revenue", moneyFmt(sum(rows, "revenue")))}
      ${metricCard("Clicks", numberFmt(sum(rows, "clicks")))}
      ${metricCard("Orders", numberFmt(sum(rows, "orders")))}
      ${metricCard("Avg ACOS", `${numberFmt(avg(rows, "acos") * 100, 2)}%`)}
    </section>
    ${chartHtml("Ad Cost by Day", groupSeries(rows, "day", "cost"), "var(--md-sys-color-warning)")}
    <section class="panel">
      <h3>Ads Daily</h3>
      ${tableHtml(rows, ["day", "marketplace", "account_id", "campaign_id", "impressions", "clicks", "cost", "orders", "revenue", "acos", "romi"])}
    </section>
    ${rawPanel("Raw /api/v1/ads/daily", result)}
  `;
}

async function renderKpis() {
  const result = await request("/api/v1/kpis", { query: commonParams(false) });
  const rows = result.items || [];
  return `
    <section class="cards">
      ${metricCard("Rows", numberFmt(rows.length))}
      ${metricCard("Revenue 30d", moneyFmt(sum(rows, "revenue_30d")))}
      ${metricCard("Qty 30d", numberFmt(sum(rows, "qty_30d")))}
      ${metricCard("Returns 30d", numberFmt(sum(rows, "returns_30d")))}
      ${metricCard("Ads Cost 30d", moneyFmt(sum(rows, "cost_30d")))}
    </section>
    <section class="panel">
      <h3>KPI 30d</h3>
      ${tableHtml(rows, ["marketplace", "account_id", "revenue_30d", "qty_30d", "returns_30d", "cost_30d", "acos_30d"])}
    </section>
    ${rawPanel("Raw /api/v1/kpis", result)}
  `;
}

async function renderWatermarks() {
  const result = await request("/api/v1/admin/watermarks", { admin: true });
  const rows = result.items || [];
  return `
    <section class="cards">
      ${metricCard("Rows", numberFmt(rows.length))}
      ${metricCard("Distinct Sources", numberFmt(new Set(rows.map((row) => row.source)).size))}
      ${metricCard("Distinct Accounts", numberFmt(new Set(rows.map((row) => row.account_id)).size))}
    </section>
    <section class="panel">
      <h3>Admin Watermarks</h3>
      ${tableHtml(rows, ["source", "account_id", "watermark_ts", "updated_at"])}
    </section>
    ${rawPanel("Raw /api/v1/admin/watermarks", result)}
  `;
}

async function renderTaskRuns() {
  const limit = Number(state.filters.taskRunsLimit || 200);
  const result = await request("/api/v1/admin/task-runs", { admin: true, query: { limit } });
  const rows = result.items || [];
  const failed = rows.filter((row) => String(row.status || "").toLowerCase() === "failed").length;
  return `
    <section class="cards">
      ${metricCard("Rows", numberFmt(rows.length))}
      ${metricCard("Failed", numberFmt(failed))}
      ${metricCard("Success", numberFmt(rows.filter((row) => String(row.status || "").toLowerCase() === "success").length))}
    </section>
    <section class="panel">
      <h3>Admin Task Runs</h3>
      ${tableHtml(rows, ["task_name", "run_id", "started_at", "finished_at", "status", "rows_ingested", "message", "meta_json"])}
    </section>
    ${rawPanel("Raw /api/v1/admin/task-runs", result)}
  `;
}

async function renderAdminActions() {
  return `
    <section class="actions-grid">
      <section class="panel">
        <h3>Run Task</h3>
        <label class="field">
          <span>Task Name</span>
          <input id="run-task-name" type="text" value="tasks.transforms.transform_all_recent" />
        </label>
        <label class="field">
          <span>Args (JSON array)</span>
          <textarea id="run-task-args" class="mono">[]</textarea>
        </label>
        <label class="field">
          <span>Kwargs (JSON object)</span>
          <textarea id="run-task-kwargs" class="mono">{}</textarea>
        </label>
        <button id="run-task-submit" class="button button-primary" type="button">Queue Task</button>
      </section>

      <section class="panel">
        <h3>Backfill</h3>
        <label class="field">
          <span>Marketplace</span>
          <select id="backfill-marketplace">
            <option value="wb">wb</option>
            <option value="ozon">ozon</option>
            <option value="marts">marts</option>
          </select>
        </label>
        <label class="field">
          <span>Dataset</span>
          <select id="backfill-dataset">
            <option value="sales">sales</option>
            <option value="orders">orders</option>
            <option value="funnel">funnel</option>
            <option value="postings">postings</option>
            <option value="finance">finance</option>
            <option value="build">build</option>
          </select>
        </label>
        <label class="field">
          <span>Days</span>
          <input id="backfill-days" type="number" min="1" max="365" value="14" />
        </label>
        <button id="backfill-submit" class="button button-primary" type="button">Run Backfill</button>
      </section>
    </section>

    <section class="panel">
      <h3>Last Admin Response</h3>
      <pre id="admin-response" class="mono">No actions yet</pre>
    </section>
  `;
}

async function renderSystem() {
  const health = await safeCall(() => request("/health"));
  const ready = await safeCall(() => request("/ready"));
  const metrics = await safeCall(() => request("/metrics", { expectText: true }));

  const metricsLines = metrics.ok
    ? metrics.data
        .split("\n")
        .filter((line) => line && !line.startsWith("#"))
        .slice(0, 120)
    : [];

  return `
    <section class="cards">
      ${metricCard("Health", health.ok ? statusChip(true, "OK") : statusChip(false), health.ok ? "GET /health" : health.error)}
      ${metricCard("Readiness", ready.ok ? statusChip(true, "Ready") : statusChip(false), ready.ok ? "GET /ready" : ready.error)}
      ${metricCard("Metrics", metrics.ok ? statusChip(true, "Available") : statusChip(false), metrics.ok ? `${numberFmt(metricsLines.length)} metric lines` : metrics.error)}
    </section>

    <section class="panel">
      <h3>Prometheus Metrics (sample)</h3>
      <pre class="mono">${escapeHtml(metrics.ok ? metricsLines.join("\n") : metrics.error)}</pre>
    </section>

    ${rawPanel("Raw /health", health.ok ? health.data : { error: health.error })}
    ${rawPanel("Raw /ready", ready.ok ? ready.data : { error: ready.error })}
  `;
}

function attachAdminActionHandlers() {
  const runTaskButton = document.getElementById("run-task-submit");
  const backfillButton = document.getElementById("backfill-submit");
  const output = document.getElementById("admin-response");

  const writeOutput = (payload) => {
    if (!output) {
      return;
    }
    output.textContent = JSON.stringify(payload, null, 2);
  };

  runTaskButton?.addEventListener("click", async () => {
    try {
      const taskName = document.getElementById("run-task-name")?.value || "";
      const argsText = document.getElementById("run-task-args")?.value || "[]";
      const kwargsText = document.getElementById("run-task-kwargs")?.value || "{}";
      const args = JSON.parse(argsText);
      const kwargs = JSON.parse(kwargsText);

      const response = await request("/api/v1/admin/run-task", {
        admin: true,
        method: "POST",
        body: {
          task_name: taskName,
          args,
          kwargs,
        },
      });
      setFeedback("Task queued successfully", "success");
      writeOutput(response);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setFeedback(`Run task failed: ${message}`, "error");
      writeOutput({ error: message });
    }
  });

  backfillButton?.addEventListener("click", async () => {
    try {
      const marketplace = document.getElementById("backfill-marketplace")?.value || "wb";
      const dataset = document.getElementById("backfill-dataset")?.value || "sales";
      const days = Number(document.getElementById("backfill-days")?.value || 14);
      const response = await request("/api/v1/admin/backfill", {
        admin: true,
        method: "POST",
        body: { marketplace, dataset, days },
      });
      setFeedback("Backfill queued successfully", "success");
      writeOutput(response);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setFeedback(`Backfill failed: ${message}`, "error");
      writeOutput({ error: message });
    }
  });
}

async function loadPage() {
  const pageDef = activePageDef();
  refs.pageTitle.textContent = pageDef.title;
  refs.pageSubtitle.textContent = pageDef.subtitle;
  renderFilters(pageDef);
  renderNav();

  refs.pageContent.innerHTML = '<section class="panel">Loading...</section>';
  if (state.page !== "dashboard") {
    setFeedback("");
  }

  try {
    let html = "";
    if (state.page === "dashboard") {
      html = await renderDashboard();
    } else if (state.page === "sales") {
      html = await renderSales();
    } else if (state.page === "stocks") {
      html = await renderStocks();
    } else if (state.page === "funnel") {
      html = await renderFunnel();
    } else if (state.page === "ads") {
      html = await renderAds();
    } else if (state.page === "kpis") {
      html = await renderKpis();
    } else if (state.page === "watermarks") {
      html = await renderWatermarks();
    } else if (state.page === "taskRuns") {
      html = await renderTaskRuns();
    } else if (state.page === "adminActions") {
      html = await renderAdminActions();
    } else if (state.page === "system") {
      html = await renderSystem();
    }
    refs.pageContent.innerHTML = html;
    if (state.page === "adminActions") {
      attachAdminActionHandlers();
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    refs.pageContent.innerHTML = `
      <section class="panel">
        <h3>Ошибка загрузки страницы</h3>
        <p class="mono">${escapeHtml(message)}</p>
      </section>
    `;
    setFeedback(message, "error");
  }
}

function loadSettings() {
  state.apiBase = normalizeBaseUrl(localStorage.getItem(STORE_KEYS.apiBase) || "");
  state.adminKey = localStorage.getItem(STORE_KEYS.adminKey) || "";
  refs.apiBaseInput.value = state.apiBase;
  refs.adminKeyInput.value = state.adminKey;

  const theme = localStorage.getItem(STORE_KEYS.theme) || "light";
  document.documentElement.dataset.theme = theme;
}

function bindGlobalControls() {
  refs.saveSettingsButton.addEventListener("click", () => {
    state.apiBase = normalizeBaseUrl(refs.apiBaseInput.value);
    state.adminKey = refs.adminKeyInput.value;
    localStorage.setItem(STORE_KEYS.apiBase, state.apiBase);
    localStorage.setItem(STORE_KEYS.adminKey, state.adminKey);
    setFeedback("Settings saved", "success");
    loadPage();
  });

  refs.reloadButton.addEventListener("click", () => {
    loadPage();
  });

  refs.themeToggle.addEventListener("click", () => {
    const current = document.documentElement.dataset.theme || "light";
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem(STORE_KEYS.theme, next);
  });

  refs.menuToggle.addEventListener("click", () => {
    refs.appShell.classList.toggle("nav-open");
  });

  window.addEventListener("hashchange", () => {
    parseHash();
    loadPage();
  });
}

function init() {
  parseHash();
  loadSettings();
  bindGlobalControls();
  loadPage();
}

init();
