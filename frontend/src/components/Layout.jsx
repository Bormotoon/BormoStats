import { useState, useEffect } from "react";
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
  MoonStars,
  Sun,
  ArrowClockwise,
} from "@phosphor-icons/react";

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

function getPageFromHash() {
  const hash = window.location.hash.replace(/^#\//, "") || "dashboard";
  return hash.split("/")[0].split("?")[0];
}

export default function Layout({ children, onReload }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [theme, setThemeState] = useState("light");
  const [currentPath, setCurrentPath] = useState(getPageFromHash);

  useEffect(() => {
    const onHashChange = () => setCurrentPath(getPageFromHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setThemeState(next);
  };

  return (
    <div className="flex h-full bg-[var(--color-surface)]">
      <AnimatePresence>
        {sidebarOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-30 bg-black/20 lg:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}
      </AnimatePresence>

      <aside
        className={`fixed lg:static inset-y-0 left-0 z-40 w-64 flex flex-col border-r border-[var(--color-outline-variant)] bg-white transition-transform duration-300 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        }`}
      >
        <div className="flex items-center gap-3 px-4 pt-5 pb-4 border-b border-[var(--color-outline-variant)]">
          <div className="w-9 h-9 rounded-xl bg-[var(--color-primary)] flex items-center justify-center font-extrabold text-sm text-white shrink-0">
            BS
          </div>
          <div>
            <p className="font-bold text-sm leading-tight text-[var(--color-on-surface)]">BormoStats</p>
            <p className="text-xs text-[var(--color-on-surface-variant)] mt-0.5">Marketplace Analytics</p>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto px-2 py-3 space-y-0.5">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const isActive = currentPath === item.id;
            return (
              <a
                key={item.id}
                href={`#/${item.id}`}
                onClick={() => setSidebarOpen(false)}
                className={`flex items-center gap-3 px-3 py-2 rounded-xl text-sm font-medium transition-all duration-150 ${
                  isActive
                    ? "bg-[var(--color-primary-container)] text-[var(--color-on-primary-container)]"
                    : "text-[var(--color-on-surface-variant)] hover:bg-[var(--color-surface-container)] hover:text-[var(--color-on-surface)]"
                }`}
              >
                <Icon size={18} weight={isActive ? "fill" : "regular"} />
                <span>{item.label}</span>
              </a>
            );
          })}
        </nav>

        <div className="px-2 pb-3">
          <button
            onClick={() => setSettingsOpen(!settingsOpen)}
            className={`flex items-center gap-3 w-full px-3 py-2 rounded-xl text-sm font-medium transition-all duration-150 ${
              settingsOpen
                ? "bg-[var(--color-primary-container)] text-[var(--color-on-primary-container)]"
                : "text-[var(--color-on-surface-variant)] hover:bg-[var(--color-surface-container)] hover:text-[var(--color-on-surface)]"
            }`}
          >
            <Gear size={18} weight={settingsOpen ? "fill" : "regular"} />
            <span>Settings</span>
          </button>
        </div>

        <AnimatePresence>
          {settingsOpen && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden border-t border-[var(--color-outline-variant)]"
            >
              <div className="px-4 py-3 space-y-3">
                <label className="block">
                  <span className="text-xs font-semibold text-[var(--color-on-surface-variant)] block mb-1.5">API Base URL</span>
                  <input
                    type="text"
                    defaultValue={(() => { try { return localStorage.getItem("bormostats_ui_api_base") || ""; } catch { return ""; } })()}
                    onChange={(e) => { try { localStorage.setItem("bormostats_ui_api_base", e.target.value.replace(/\/+$/, "")); } catch {} }}
                    placeholder="http://localhost:18080"
                    className="w-full px-3 py-2 rounded-lg bg-[var(--color-surface-container)] border border-[var(--color-outline-variant)] text-sm text-[var(--color-on-surface)] placeholder:text-[var(--color-on-surface-variant)] focus:outline-none focus:border-[var(--color-primary)]"
                  />
                </label>
                <label className="block">
                  <span className="text-xs font-semibold text-[var(--color-on-surface-variant)] block mb-1.5">Admin API Key</span>
                  <input
                    type="password"
                    onChange={(e) => {
                      if (e.target.value.trim()) {
                        try { sessionStorage.setItem("bormostats_admin_key", e.target.value.trim()); } catch {}
                      } else {
                        try { sessionStorage.removeItem("bormostats_admin_key"); } catch {}
                      }
                    }}
                    placeholder="X-API-Key"
                    className="w-full px-3 py-2 rounded-lg bg-[var(--color-surface-container)] border border-[var(--color-outline-variant)] text-sm text-[var(--color-on-surface)] placeholder:text-[var(--color-on-surface-variant)] focus:outline-none focus:border-[var(--color-primary)]"
                  />
                </label>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </aside>

      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <header className="flex items-center justify-between gap-4 px-4 lg:px-6 py-3 border-b border-[var(--color-outline-variant)] bg-white shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <button
              onClick={() => setSidebarOpen(true)}
              className="lg:hidden p-2 rounded-lg hover:bg-[var(--color-surface-container)] text-[var(--color-on-surface-variant)]"
            >
              <List size={20} />
            </button>
            <div className="min-w-0">
              <h1 className="text-lg font-bold tracking-tight text-[var(--color-on-surface)] truncate">
                {PAGE_TITLES[currentPath] || "Dashboard"}
              </h1>
              <p className="text-xs text-[var(--color-on-surface-variant)] truncate mt-0.5">
                {pageSubtitles[currentPath] || ""}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1 shrink-0">
            <button
              onClick={onReload}
              className="p-2 rounded-lg hover:bg-[var(--color-surface-container)] text-[var(--color-on-surface-variant)] transition-colors"
              title="Reload data"
            >
              <ArrowClockwise size={18} />
            </button>
            <button
              onClick={toggleTheme}
              className="p-2 rounded-lg hover:bg-[var(--color-surface-container)] text-[var(--color-on-surface-variant)] transition-colors"
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
