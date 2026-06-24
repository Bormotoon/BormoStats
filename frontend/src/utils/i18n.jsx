import { createContext, useContext, useState, useEffect, useCallback } from "react";

const LANG_KEY = "bormostats_ui_lang";

const ru = {
  brand: { name: "BormoStats", tagline: "Аналитика маркетплейсов" },
  nav: {
    dashboard: "Дашборд", sales: "Продажи", stocks: "Остатки",
    funnel: "Воронка", ads: "Реклама", bidder: "Биддер",
    repricer: "Репрайсер", pnl: "P&L", kpis: "KPI",
    watermarks: "Водяные знаки", taskRuns: "Запуски задач",
    adminActions: "Админ", system: "Система",
  },
  pageTitles: {
    dashboard: "Дашборд", sales: "Продажи", stocks: "Остатки",
    funnel: "Воронка", ads: "Реклама", bidder: "Биддер",
    repricer: "Репрайсер", pnl: "P&L", kpis: "KPI",
    watermarks: "Водяные знаки", taskRuns: "Запуски задач",
    adminActions: "Действия админа", system: "Система",
  },
  pageSubtitles: {
    bidder: "Управление ставками рекламных кампаний",
    repricer: "Динамическое ценообразование и break-even",
    pnl: "Прибыли и убытки (P&L)",
    dashboard: "Продажи, реклама, остатки и статус сервисов",
    sales: "Дневные продажи из mrt_sales_daily",
    stocks: "Текущие остатки по последнему дню из mrt_stock_daily",
    funnel: "Воронка карточки: просмотры, корзина, заказы, конверсии",
    ads: "Метрики рекламы: cost, revenue, ACOS, ROMI",
    kpis: "KPI за 30 дней по маркетплейсу / аккаунту",
    watermarks: "Системные водяные знаки ингрестации (admin)",
    taskRuns: "История запусков задач workers (admin)",
    adminActions: "Whitelist операции админа: backfill, rebuild, maintenance",
    system: "Health, readiness, метрики Prometheus",
  },
  common: {
    loading: "Загрузка…", noData: "Нет данных", error: "Ошибка",
    rows: "Записей", reload: "Обновить", settings: "Настройки",
    apiBaseUrl: "API Base URL", adminApiKey: "Admin API Key",
    placeholderApi: "http://localhost:18080", placeholderKey: "X-API-Key",
    keyNote: "Admin key хранится только в памяти вкладки (sessionStorage). После закрытия вкладки key очищается.",
    save: "Сохранить", saved: "Сохранено",
    health: "Health", ready: "Ready",
    healthy: "Здоров", unhealthy: "Нездоров",
    readyStatus: "Готов", notReady: "Не готов",
    success: "Успех", warning: "Внимание", error_acid: "Ошибка", info: "Инфо",
    available: "Доступно", unavailable: "Недоступно",
    language: "Язык",
    notFound: "Страница не найдена",
    navigateSidebar: "Используйте боковое меню для навигации",
  },
  filters: {
    dateFrom: "Дата от", dateTo: "Дата до",
    marketplace: "Маркетплейс", accountId: "ID аккаунта",
    limit: "Лимит", taskRunsLimit: "Лимит задач",
    all: "Все", reset: "Сбросить",
  },
  dashboard: {
    stockUnits: "Ед. остатков", stockItems: "Товаров",
    revenue: "Выручка", salesQty: "Кол-во продаж", adCost: "Расходы на рекламу",
    period: "за период", sumQty: "сумма qty", sumCost: "сумма cost",
    items: "позиций", uniqueProducts: "уникальных товаров",
    revenueTrend: "Динамика выручки", adSpendTrend: "Динамика расходов на рекламу",
    topProducts: "Топ товаров по выручке",
  },
  sales: {
    revenue: "Выручка", qty: "Кол-во", returns: "Возвраты", payout: "К выплате",
    revenueByDay: "Выручка по дням", salesDaily: "Продажи по дням",
    empty: "Нет данных по продажам за выбранный период",
  },
  stocks: {
    totalStock: "Всего остатков", rows: "Записей",
    lowStock: "Малый остаток (≤5)", warehouses: "Складов",
    topByStock: "Топ товаров по остаткам", currentStocks: "Текущие остатки",
    empty: "Нет данных по остаткам",
  },
  funnel: {
    views: "Просмотры", addsToCart: "В корзину", orders: "Заказы",
    avgCrOrder: "Ср. CR заказа", avgCrCart: "Ср. CR корзины",
    conversionRate: "Конверсия", ordersByDay: "Заказы по дням",
    funnelDaily: "Воронка по дням",
    empty: "Нет данных по воронке за выбранный период",
  },
  ads: {
    cost: "Расходы", revenue: "Доход", clicks: "Клики",
    orders: "Заказы", avgAcos: "Ср. ACOS",
    costByDay: "Расходы по дням", revenueByDay: "Доход по дням",
    adsDaily: "Реклама по дням",
    empty: "Нет данных по рекламе за выбранный период",
  },
  kpis: {
    revenue30d: "Выручка 30д", qty30d: "Кол-во 30д",
    returns30d: "Возвраты 30д", adsCost30d: "Расходы на рекламу 30д",
    accounts: "Аккаунтов",
    revenueByAccount: "Выручка за 30д по аккаунтам", kpi30d: "KPI за 30 дней",
    empty: "Нет KPI данных",
  },
  watermarks: {
    rows: "Записей", distinctSources: "Источников", distinctAccounts: "Аккаунтов",
    title: "Водяные знаки",
    empty: "Водяные знаки не найдены (admin endpoint)",
  },
  taskRuns: {
    totalRuns: "Всего запусков", success: "Успешно", failed: "Ошибок",
    successRate: "Процент успеха", title: "Запуски задач",
    empty: "Запуски задач не найдены",
  },
  adminActions: {
    keyRequired: "Требуется Admin Key",
    keyRequiredDesc: "Установите Admin API ключ в Настройках (боковая панель) для использования этих операций.",
    action: "Действие", days: "Дней", execute: "Выполнить", executing: "Выполнение…",
    response: "Ответ", completed: "выполнено успешно",
    actionLabels: {
      backfill_wb_sales: "WB Sales Backfill", backfill_wb_orders: "WB Orders Backfill",
      backfill_wb_funnel: "WB Funnel Backfill", backfill_ozon_postings: "Ozon Postings Backfill",
      backfill_ozon_finance: "Ozon Finance Backfill", transform_recent: "Transform Recent",
      transform_backfill: "Transform Backfill", marts_recent: "Marts Recent",
      marts_backfill: "Marts Backfill", run_automation: "Run Automation Rules",
      prune_raw: "Prune Old Raw",
    },
    actionDescs: {
      backfill_wb_sales: "Перезапустить сбор сырых данных WB sales за указанный период",
      backfill_wb_orders: "Перезапустить сбор WB orders до 90 дней",
      backfill_wb_funnel: "Пересобрать сырые данные WB funnel",
      backfill_ozon_postings: "Перезапустить сбор Ozon postings",
      backfill_ozon_finance: "Перезапустить сбор Ozon finance",
      transform_recent: "Пересобрать недавние преобразования",
      transform_backfill: "Пересобрать staging таблицы за период",
      marts_recent: "Пересобрать недавние витрины",
      marts_backfill: "Пересобрать витрины за период",
      run_automation: "Запустить правила автоматизации вне расписания",
      prune_raw: "Удалить старые сырые записи старше срока хранения",
    },
  },
  system: {
    health: "Health", readiness: "Readiness", metrics: "Metrics",
    rawHealth: "Raw /health", rawReady: "Raw /ready",
    promMetrics: "Prometheus Metrics (образец)",
    metricLines: "метрик",
  },
};

const en = {
  brand: { name: "BormoStats", tagline: "Marketplace Analytics" },
  nav: {
    dashboard: "Dashboard", sales: "Sales", stocks: "Stocks",
    funnel: "Funnel", ads: "Ads", bidder: "Bidder",
    repricer: "Repricer", pnl: "P&L", kpis: "KPIs",
    watermarks: "Watermarks", taskRuns: "Task Runs",
    adminActions: "Admin", system: "System",
  },
  pageTitles: {
    dashboard: "Dashboard", sales: "Sales", stocks: "Stocks",
    funnel: "Funnel", ads: "Ads", bidder: "Bidder",
    repricer: "Repricer", pnl: "P&L", kpis: "KPIs",
    watermarks: "Watermarks", taskRuns: "Task Runs",
    adminActions: "Admin Actions", system: "System",
  },
  pageSubtitles: {
    bidder: "Ad campaign bid management",
    repricer: "Dynamic pricing and break-even analysis",
    pnl: "Profit & Loss statement",
    dashboard: "Sales, ads, stocks, and service status at a glance",
    sales: "Daily sales from mrt_sales_daily",
    stocks: "Current stock by the latest day in mrt_stock_daily",
    funnel: "Card funnel: views, cart, orders, conversion rates",
    ads: "Advertising metrics: cost, revenue, ACOS, ROMI",
    kpis: "30d KPIs by marketplace / account",
    watermarks: "System ingestion watermarks (admin)",
    taskRuns: "Worker task run history (admin)",
    adminActions: "Whitelisted admin operations: backfill, rebuild, maintenance",
    system: "Health, readiness, and Prometheus metrics",
  },
  common: {
    loading: "Loading…", noData: "No data", error: "Error",
    rows: "Rows", reload: "Reload", settings: "Settings",
    apiBaseUrl: "API Base URL", adminApiKey: "Admin API Key",
    placeholderApi: "http://localhost:18080", placeholderKey: "X-API-Key",
    keyNote: "Admin key is stored in session memory only. It must be re-entered after closing the tab.",
    save: "Save", saved: "Saved",
    health: "Health", ready: "Ready",
    healthy: "Healthy", unhealthy: "Unhealthy",
    readyStatus: "Ready", notReady: "Not Ready",
    success: "Success", warning: "Warning", error_acid: "Error", info: "Info",
    available: "Available", unavailable: "Unavailable",
    language: "Language",
    notFound: "Page not found",
    navigateSidebar: "Navigate using the sidebar",
  },
  filters: {
    dateFrom: "Date From", dateTo: "Date To",
    marketplace: "Marketplace", accountId: "Account ID",
    limit: "Limit", taskRunsLimit: "Task Runs Limit",
    all: "All", reset: "Reset",
  },
  dashboard: {
    stockUnits: "Stock Units", stockItems: "Stock Items",
    revenue: "Revenue", salesQty: "Sales Qty", adCost: "Ad Cost",
    period: "for period", sumQty: "total qty", sumCost: "total cost",
    items: "items", uniqueProducts: "unique products",
    revenueTrend: "Revenue Trend", adSpendTrend: "Ad Spend Trend",
    topProducts: "Top Products by Revenue",
  },
  sales: {
    revenue: "Revenue", qty: "Qty", returns: "Returns", payout: "Payout",
    revenueByDay: "Revenue by Day", salesDaily: "Sales Daily",
    empty: "No sales data for the selected period",
  },
  stocks: {
    totalStock: "Total Stock", rows: "Rows",
    lowStock: "Low Stock (≤5)", warehouses: "Warehouses",
    topByStock: "Top Products by Stock", currentStocks: "Current Stocks",
    empty: "No stock data available",
  },
  funnel: {
    views: "Views", addsToCart: "Adds to Cart", orders: "Orders",
    avgCrOrder: "Avg CR Order", avgCrCart: "Avg CR Cart",
    conversionRate: "Conversion Rate", ordersByDay: "Orders by Day",
    funnelDaily: "Funnel Daily",
    empty: "No funnel data for the selected period",
  },
  ads: {
    cost: "Cost", revenue: "Revenue", clicks: "Clicks",
    orders: "Orders", avgAcos: "Avg ACOS",
    costByDay: "Ad Cost by Day", revenueByDay: "Ad Revenue by Day",
    adsDaily: "Ads Daily",
    empty: "No ad data for the selected period",
  },
  kpis: {
    revenue30d: "Revenue 30d", qty30d: "Qty 30d",
    returns30d: "Returns 30d", adsCost30d: "Ads Cost 30d",
    accounts: "Accounts",
    revenueByAccount: "Revenue 30d by Account", kpi30d: "KPI 30d",
    empty: "No KPI data",
  },
  watermarks: {
    rows: "Rows", distinctSources: "Distinct Sources", distinctAccounts: "Distinct Accounts",
    title: "Watermarks",
    empty: "No watermarks found (admin endpoint)",
  },
  taskRuns: {
    totalRuns: "Total Runs", success: "Success", failed: "Failed",
    successRate: "Success Rate", title: "Task Runs",
    empty: "No task runs found",
  },
  adminActions: {
    keyRequired: "Admin Key Required",
    keyRequiredDesc: "Set the Admin API key in Settings (sidebar) to use these operations.",
    action: "Action", days: "Days", execute: "Execute Action", executing: "Executing…",
    response: "Response", completed: "completed successfully",
    actionLabels: {
      backfill_wb_sales: "WB Sales Backfill", backfill_wb_orders: "WB Orders Backfill",
      backfill_wb_funnel: "WB Funnel Backfill", backfill_ozon_postings: "Ozon Postings Backfill",
      backfill_ozon_finance: "Ozon Finance Backfill", transform_recent: "Transform Recent",
      transform_backfill: "Transform Backfill", marts_recent: "Marts Recent",
      marts_backfill: "Marts Backfill", run_automation: "Run Automation Rules",
      prune_raw: "Prune Old Raw",
    },
    actionDescs: {
      backfill_wb_sales: "Requeue WB sales raw for a bounded window",
      backfill_wb_orders: "Requeue WB orders for up to 90 days",
      backfill_wb_funnel: "Rebuild WB funnel raw data",
      backfill_ozon_postings: "Requeue Ozon postings ingestion",
      backfill_ozon_finance: "Requeue Ozon finance ingestion",
      transform_recent: "Rebuild recent transform window",
      transform_backfill: "Rebuild staging tables for a day window",
      marts_recent: "Rebuild recent marts",
      marts_backfill: "Rebuild marts for a day window",
      run_automation: "Trigger alert automation outside schedule",
      prune_raw: "Delete raw records older than retention",
    },
  },
  system: {
    health: "Health", readiness: "Readiness", metrics: "Metrics",
    rawHealth: "Raw /health", rawReady: "Raw /ready",
    promMetrics: "Prometheus Metrics (sample)",
    metricLines: "metric lines",
  },
};

const DICT = { ru, en };

const I18nContext = createContext();

export function I18nProvider({ children }) {
  const [lang, setLangState] = useState(() => {
    try { return localStorage.getItem(LANG_KEY) || "ru"; } catch { return "ru"; }
  });

  const setLang = useCallback((l) => {
    setLangState(l);
    try { localStorage.setItem(LANG_KEY, l); } catch {}
  }, []);

  const t = useCallback((path) => {
    const keys = path.split(".");
    let val = DICT[lang];
    for (const k of keys) {
      val = val?.[k];
    }
    return val ?? path;
  }, [lang]);

  return (
    <I18nContext.Provider value={{ lang, setLang, t }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within I18nProvider");
  return ctx;
}
