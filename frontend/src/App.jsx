import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "motion/react";
import { I18nProvider, useI18n } from "./utils/i18n.jsx";
import Layout from "./components/Layout.jsx";
import FiltersBar from "./components/FiltersBar.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Sales from "./pages/Sales.jsx";
import Stocks from "./pages/Stocks.jsx";
import Funnel from "./pages/Funnel.jsx";
import Ads from "./pages/Ads.jsx";
import Bidder from "./pages/Bidder.jsx";
import PnL from "./pages/PnL.jsx";
import Repricer from "./pages/Repricer.jsx";
import KPIs from "./pages/KPIs.jsx";
import Watermarks from "./pages/Watermarks.jsx";
import TaskRuns from "./pages/TaskRuns.jsx";
import AdminActions from "./pages/AdminActions.jsx";
import System from "./pages/System.jsx";
import { loadSettings, getTheme } from "./utils/api.js";
loadSettings();

const PAGES = {
  dashboard: Dashboard,
  sales: Sales,
  stocks: Stocks,
  funnel: Funnel,
  ads: Ads,
  bidder: Bidder,
  pnl: PnL,
  repricer: Repricer,
  kpis: KPIs,
  watermarks: Watermarks,
  taskRuns: TaskRuns,
  adminActions: AdminActions,
  system: System,
};

function getPageFromHash() {
  const hash = window.location.hash.replace(/^#\//, "") || "dashboard";
  return hash.split("/")[0].split("?")[0];
}

function AppInner() {
  const [currentPath, setCurrentPath] = useState(getPageFromHash);
  const PageComponent = PAGES[currentPath];
  const { t } = useI18n();

  useEffect(() => {
    document.documentElement.dataset.theme = getTheme();
    const onHashChange = () => setCurrentPath(getPageFromHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const handleReload = useCallback(() => {
    window.location.reload();
  }, []);

  return (
    <Layout onReload={handleReload}>
      <FiltersBar pageId={currentPath} />
      <AnimatePresence mode="wait">
        <motion.div
          key={currentPath}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -12 }}
          transition={{ duration: 0.2, ease: "easeOut" }}
        >
          {PageComponent ? (
            <PageComponent />
          ) : (
            <div className="text-center py-16 text-[var(--color-on-surface-variant)]">
              <p className="text-lg font-bold">{t("common.notFound")}</p>
              <p className="text-sm mt-2">{t("common.navigateSidebar")}</p>
            </div>
          )}
        </motion.div>
      </AnimatePresence>
    </Layout>
  );
}

export default function App() {
  return (
    <I18nProvider>
      <AppInner />
    </I18nProvider>
  );
}
