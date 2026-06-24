import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "motion/react";
import { useI18n } from "../utils/i18n.jsx";
import AccountSwitcher from "./AccountSwitcher.jsx";
import {
  ChartLineUp, ShoppingCart, Warehouse, Funnel, Megaphone,
  Target, Drop, ListChecks, ShieldCheck, Monitor, CurrencyCircleDollar, Tag,
  Gear, List, MoonStars, Sun, ArrowClockwise, Translate,
} from "@phosphor-icons/react";

const NAV_ITEMS = [
  { id: "dashboard", icon: ChartLineUp },
  { id: "sales", icon: ShoppingCart },
  { id: "stocks", icon: Warehouse },
  { id: "funnel", icon: Funnel },
  { id: "ads", icon: Megaphone },
  { id: "bidder", icon: CurrencyCircleDollar },
  { id: "repricer", icon: Tag },
  { id: "kpis", icon: Target },
  { id: "watermarks", icon: Drop },
  { id: "taskRuns", icon: ListChecks },
  { id: "adminActions", icon: ShieldCheck },
  { id: "system", icon: Monitor },
];

function getPageFromHash() {
  const hash = window.location.hash.replace(/^#\//, "") || "dashboard";
  return hash.split("/")[0].split("?")[0];
}

export default function Layout({ children, onReload }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [currentPath, setCurrentPath] = useState(getPageFromHash);
  const { t, lang, setLang } = useI18n();

  useEffect(() => {
    const onHashChange = () => setCurrentPath(getPageFromHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const [apiBase, setApiBase] = useState(() => {
    try { return localStorage.getItem("bormostats_ui_api_base") || ""; } catch { return ""; }
  });

  const [adminKeyInput, setAdminKeyInput] = useState("");

  const saveApiBase = (val) => {
    setApiBase(val);
    try { localStorage.setItem("bormostats_ui_api_base", val.replace(/\/+$/, "")); } catch {}
  };

  const saveAdminKey = (val) => {
    setAdminKeyInput(val);
    if (val.trim()) {
      try { sessionStorage.setItem("bormostats_admin_key", val.trim()); } catch {}
    } else {
      try { sessionStorage.removeItem("bormostats_admin_key"); } catch {}
    }
  };

  const toggleLang = () => setLang(lang === "ru" ? "en" : "ru");

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
            <p className="font-bold text-sm leading-tight text-[var(--color-on-surface)]">{t("brand.name")}</p>
            <p className="text-xs text-[var(--color-on-surface-variant)] mt-0.5">{t("brand.tagline")}</p>
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
                <span>{t(`nav.${item.id}`)}</span>
              </a>
            );
          })}
        </nav>

        <div className="px-2 pb-3 space-y-0.5">
          <button
            onClick={() => setSettingsOpen(!settingsOpen)}
            className={`flex items-center gap-3 w-full px-3 py-2 rounded-xl text-sm font-medium transition-all duration-150 ${
              settingsOpen
                ? "bg-[var(--color-primary-container)] text-[var(--color-on-primary-container)]"
                : "text-[var(--color-on-surface-variant)] hover:bg-[var(--color-surface-container)] hover:text-[var(--color-on-surface)]"
            }`}
          >
            <Gear size={18} weight={settingsOpen ? "fill" : "regular"} />
            <span>{t("common.settings")}</span>
          </button>
          <button
            onClick={toggleLang}
            className="flex items-center gap-3 w-full px-3 py-2 rounded-xl text-sm font-medium text-[var(--color-on-surface-variant)] hover:bg-[var(--color-surface-container)] hover:text-[var(--color-on-surface)] transition-all duration-150"
          >
            <Translate size={18} />
            <span>{lang === "ru" ? "English" : "Русский"}</span>
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
                  <span className="text-xs font-semibold text-[var(--color-on-surface-variant)] block mb-1.5">{t("common.apiBaseUrl")}</span>
                  <input
                    type="text"
                    value={apiBase}
                    onChange={(e) => saveApiBase(e.target.value)}
                    placeholder={t("common.placeholderApi")}
                    className="w-full px-3 py-2 rounded-lg bg-[var(--color-surface-container)] border border-[var(--color-outline-variant)] text-sm text-[var(--color-on-surface)] placeholder:text-[var(--color-on-surface-variant)] focus:outline-none focus:border-[var(--color-primary)]"
                  />
                </label>
                <label className="block">
                  <span className="text-xs font-semibold text-[var(--color-on-surface-variant)] block mb-1.5">{t("common.adminApiKey")}</span>
                  <input
                    type="password"
                    value={adminKeyInput}
                    onChange={(e) => saveAdminKey(e.target.value)}
                    placeholder={t("common.placeholderKey")}
                    className="w-full px-3 py-2 rounded-lg bg-[var(--color-surface-container)] border border-[var(--color-outline-variant)] text-sm text-[var(--color-on-surface)] placeholder:text-[var(--color-on-surface-variant)] focus:outline-none focus:border-[var(--color-primary)]"
                  />
                </label>
                <p className="text-xs text-[var(--color-on-surface-variant)] leading-relaxed">{t("common.keyNote")}</p>
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
                {t(`pageTitles.${currentPath}`)}
              </h1>
              <p className="text-xs text-[var(--color-on-surface-variant)] truncate mt-0.5">
                {t(`pageSubtitles.${currentPath}`)}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <AccountSwitcher />
            <button
              onClick={onReload}
              className="p-2 rounded-lg hover:bg-[var(--color-surface-container)] text-[var(--color-on-surface-variant)] transition-colors"
              title={t("common.reload")}
            >
              <ArrowClockwise size={18} />
            </button>
            <button
              onClick={toggleLang}
              className="p-2 rounded-lg hover:bg-[var(--color-surface-container)] text-[var(--color-on-surface-variant)] transition-colors"
              title={t("common.language")}
            >
              <Translate size={18} />
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
