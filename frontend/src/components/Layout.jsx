import { useRef, useState, useEffect } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { motion, AnimatePresence } from "motion/react";
import {
  ChartLineUp,
  ShoppingCart,
  Warehouse,
  Funnel,
  Megaphone,
  Target,
  Drop,
  ListChecks,
  ShieldCheck,
  Monitor,
  Gear,
  List,
  X,
  MoonStars,
  Sun,
  ArrowClockwise,
} from "@phosphor-icons/react";
import { getTheme, setTheme } from "../utils/api";

const NAV_ITEMS = [
  { id: "dashboard", label: "Dashboard", icon: ChartLineUp },
  { id: "sales", label: "Sales", icon: ShoppingCart },
  { id: "stocks", label: "Stocks", icon: Warehouse },
  { id: "funnel", label: "Funnel", icon: Funnel },
  { id: "ads", label: "Ads", icon: Megaphone },
  { id: "kpis", label: "KPIs", icon: Target },
  { id: "watermarks", label: "Watermarks", icon: Drop },
  { id: "taskRuns", label: "Task Runs", icon: ListChecks },
  { id: "adminActions", label: "Admin", icon: ShieldCheck },
  { id: "system", label: "System", icon: Monitor },
];

const pageSubtitles = {
  dashboard: "Операционная сводка по продажам, рекламе и состоянию сервисов",
  sales: "Дневные продажи по витрине mrt_sales_daily",
  stocks: "Текущие остатки по последнему дню в mrt_stock_daily",
  funnel: "Воронка карточки: просмотры, корзина, заказы, конверсии",
  ads: "Рекламные метрики: cost, revenue, ACOS, ROMI",
  kpis: "KPI 30d по marketplace/account",
  watermarks: "Системные водяные знаки ingestion (admin)",
  taskRuns: "История запусков задач workers (admin)",
  adminActions: "Whitelist admin operations: backfill, rebuild и maintenance",
  system: "Health, readiness и Prometheus metrics",
};

const PAGE_TITLES = {
  dashboard: "Dashboard",
  sales: "Sales",
  stocks: "Stocks",
  funnel: "Funnel",
  ads: "Ads",
  kpis: "KPIs",
  watermarks: "Watermarks",
  taskRuns: "Task Runs",
  adminActions: "Admin Actions",
  system: "System",
};

export default function Layout({ children, title, onReload }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [theme, setThemeState] = useState(getTheme());
  const location = useLocation();
  const currentPath = location.pathname.replace(/^\//, "") || "dashboard";

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    setThemeState(next);
  };

  return (
    <div className="flex h-full">
      <AnimatePresence>
        {sidebarOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-30 bg-black/50 lg:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}
      </AnimatePresence>

      <aside
        className={`fixed lg:static inset-y-0 left-0 z-40 w-72 flex flex-col border-r border-[var(--color-border)] nav-gradient transition-transform duration-300 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        }`}
      >
        <div className="flex items-center gap-3 px-5 pt-5 pb-4 border-b border-[var(--color-border)]">
          <div className="w-10 h-10 rounded-xl bg-[var(--color-brand)] flex items-center justify-center font-extrabold text-sm text-white shrink-0">
            BS
          </div>
          <div>
            <p className="font-extrabold text-sm leading-tight">BormoStats</p>
            <p className="text-xs text-[var(--color-text-muted)] mt-0.5">Marketplace Analytics</p>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-1">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const isActive = currentPath === item.id;
            return (
              <NavLink
                key={item.id}
                to={`/${item.id}`}
                onClick={() => setSidebarOpen(false)}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 ${
                  isActive
                    ? "bg-[var(--color-brand)]/15 text-[var(--color-brand-light)]"
                    : "text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-highest)] hover:text-[var(--color-text-primary)]"
                }`}
              >
                <Icon size={18} weight={isActive ? "fill" : "regular"} />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>

        <div className="px-3 pb-4">
          <button
            onClick={() => setSettingsOpen(!settingsOpen)}
            className={`flex items-center gap-3 w-full px-3 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 ${
              settingsOpen
                ? "bg-[var(--color-brand)]/15 text-[var(--color-brand-light)]"
                : "text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-highest)] hover:text-[var(--color-text-primary)]"
            }`}
          >
            <Gear size={18} weight={settingsOpen ? "fill" : "regular"} />
            <span>Settings</span>
          </button>
        </div>

        <AnimatePresence>
          {settingsOpen && <SettingsPanel />}
        </AnimatePresence>
      </aside>

      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <header className="flex items-center justify-between gap-4 px-4 lg:px-6 py-3 border-b border-[var(--color-border)] bg-[var(--color-surface-elevated)]/80 backdrop-blur-md shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <button
              onClick={() => setSidebarOpen(true)}
              className="lg:hidden p-2 rounded-lg hover:bg-[var(--color-surface-highest)] text-[var(--color-text-secondary)]"
            >
              <List size={20} />
            </button>
            <div className="min-w-0">
              <h1 className="text-lg font-extrabold truncate">
                {PAGE_TITLES[currentPath] || "Dashboard"}
              </h1>
              <p className="text-xs text-[var(--color-text-muted)] truncate">
                {pageSubtitles[currentPath] || ""}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={onReload}
              className="p-2 rounded-lg hover:bg-[var(--color-surface-highest)] text-[var(--color-text-secondary)] transition-colors"
              title="Reload data"
            >
              <ArrowClockwise size={18} />
            </button>
            <button
              onClick={toggleTheme}
              className="p-2 rounded-lg hover:bg-[var(--color-surface-highest)] text-[var(--color-text-secondary)] transition-colors"
              title="Toggle theme"
            >
              {theme === "dark" ? <Sun size={18} /> : <MoonStars size={18} />}
            </button>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-4 lg:p-6">
          {children}
        </div>
      </main>
    </div>
  );
}

function SettingsPanel() {
  const [apiBase, setApiBase] = useState(() => {
    try {
      return localStorage.getItem("bormostats_ui_api_base") || "";
    } catch {
      return "";
    }
  });
  const [adminKey, setAdminKeyState] = useState("");
  const [saved, setSaved] = useState(false);


  const handleSave = () => {
    try {
      localStorage.setItem("bormostats_ui_api_base", apiBase.replace(/\/+$/, ""));
      if (adminKey.trim()) {
        sessionStorage.setItem("bormostats_admin_key", adminKey.trim());
      } else {
        sessionStorage.removeItem("bormostats_admin_key");
      }
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      //
    }
  };

  return (
    <motion.div
      initial={{ height: 0, opacity: 0 }}
      animate={{ height: "auto", opacity: 1 }}
      exit={{ height: 0, opacity: 0 }}
      className="overflow-hidden border-t border-[var(--color-border)]"
    >
      <div className="px-4 py-4 space-y-3">
        <label className="block">
          <span className="text-xs font-semibold text-[var(--color-text-muted)] block mb-1.5">
            API Base URL
          </span>
          <input
            type="text"
            value={apiBase}
            onChange={(e) => setApiBase(e.target.value)}
            placeholder="http://localhost:18080"
            className="w-full px-3 py-2 rounded-lg bg-[var(--color-surface)] border border-[var(--color-border)] text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:border-[var(--color-brand)]"
          />
        </label>
        <label className="block">
          <span className="text-xs font-semibold text-[var(--color-text-muted)] block mb-1.5">
            Admin API Key
          </span>
          <input
            type="password"
            value={adminKey}
            onChange={(e) => setAdminKeyState(e.target.value)}
            placeholder="X-API-Key"
            className="w-full px-3 py-2 rounded-lg bg-[var(--color-surface)] border border-[var(--color-border)] text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:border-[var(--color-brand)]"
          />
        </label>
        <p className="text-xs text-[var(--color-text-muted)] leading-relaxed">
          Admin key хранится только в памяти вкладки (sessionStorage). После закрытия вкладки key очищается.
        </p>
        <button
          onClick={handleSave}
          className="w-full py-2 rounded-lg bg-[var(--color-brand)] text-white font-bold text-sm hover:opacity-90 transition-opacity"
        >
          {saved ? "Saved!" : "Save Settings"}
        </button>
      </div>
    </motion.div>
  );
}
