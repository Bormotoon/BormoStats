import { useState, useEffect } from "react";
import { request, getAdminKey } from "../utils/api.js";
import { useI18n } from "../utils/i18n.jsx";
import { motion } from "motion/react";

const ADMIN_ACTIONS = [
  { id: "backfill_wb_sales", endpoint: "/api/v1/admin/backfill", body: (d) => ({ marketplace: "wb", dataset: "sales", days: d }), hasDays: true, daysMin: 1, daysMax: 90, daysDefault: 14 },
  { id: "backfill_wb_orders", endpoint: "/api/v1/admin/backfill", body: (d) => ({ marketplace: "wb", dataset: "orders", days: d }), hasDays: true, daysMin: 1, daysMax: 90, daysDefault: 14 },
  { id: "backfill_wb_funnel", endpoint: "/api/v1/admin/backfill", body: (d) => ({ marketplace: "wb", dataset: "funnel", days: d }), hasDays: true, daysMin: 1, daysMax: 90, daysDefault: 14 },
  { id: "backfill_ozon_postings", endpoint: "/api/v1/admin/backfill", body: (d) => ({ marketplace: "ozon", dataset: "postings", days: d }), hasDays: true, daysMin: 1, daysMax: 90, daysDefault: 14 },
  { id: "backfill_ozon_finance", endpoint: "/api/v1/admin/backfill", body: (d) => ({ marketplace: "ozon", dataset: "finance", days: d }), hasDays: true, daysMin: 1, daysMax: 365, daysDefault: 30 },
  { id: "transform_recent", endpoint: "/api/v1/admin/transforms/recent", body: () => ({}), hasDays: false },
  { id: "transform_backfill", endpoint: "/api/v1/admin/transforms/backfill", body: (d) => ({ days: d }), hasDays: true, daysMin: 1, daysMax: 365, daysDefault: 14 },
  { id: "marts_recent", endpoint: "/api/v1/admin/marts/recent", body: () => ({}), hasDays: false },
  { id: "marts_backfill", endpoint: "/api/v1/admin/marts/backfill", body: (d) => ({ days: d }), hasDays: true, daysMin: 1, daysMax: 365, daysDefault: 14 },
  { id: "run_automation", endpoint: "/api/v1/admin/maintenance/run-automation", body: () => ({}), hasDays: false },
  { id: "prune_raw", endpoint: "/api/v1/admin/maintenance/prune-raw", body: (d) => ({ days: d }), hasDays: true, daysMin: 30, daysMax: 3650, daysDefault: 120 },
];

export default function AdminActions() {
  const { t } = useI18n();
  const [selected, setSelected] = useState(ADMIN_ACTIONS[0]);
  const [days, setDays] = useState(ADMIN_ACTIONS[0].daysDefault || 14);
  const [response, setResponse] = useState(null);
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState({ message: "", kind: "" });

  const hasKey = !!getAdminKey();

  const runAction = async () => {
    if (!hasKey) {
      setFeedback({ message: t("adminActions.keyRequiredDesc"), kind: "error" });
      return;
    }
    setLoading(true);
    setFeedback({ message: "", kind: "" });
    setResponse(null);
    try {
      const res = await request(selected.endpoint, {
        admin: true,
        method: "POST",
        body: selected.body(days),
      });
      setResponse(res);
      setFeedback({ message: `${t(`adminActions.actionLabels.${selected.id}`)} ${t("adminActions.completed")}`, kind: "success" });
    } catch (err) {
      setFeedback({ message: err.message, kind: "error" });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      {!hasKey && (
        <div className="rounded-xl border border-[var(--color-warning)]/30 bg-[var(--color-warning-container)] p-4">
          <h3 className="text-sm font-bold text-[var(--color-warning)] mb-1">{t("adminActions.keyRequired")}</h3>
          <p className="text-xs text-[var(--color-on-surface-variant)]">{t("adminActions.keyRequiredDesc")}</p>
        </div>
      )}

      <div className="md3-card-elevated p-4 space-y-4">
        <div>
          <label className="block text-xs font-semibold text-[var(--color-on-surface-variant)] mb-1.5">{t("adminActions.action")}</label>
          <select
            value={selected.id}
            onChange={(e) => {
              const action = ADMIN_ACTIONS.find((a) => a.id === e.target.value) || ADMIN_ACTIONS[0];
              setSelected(action);
              setDays(action.daysDefault || 14);
            }}
            className="w-full px-3 py-2 rounded-lg bg-[var(--color-surface-container)] border border-[var(--color-outline-variant)] text-sm text-[var(--color-on-surface)] focus:outline-none focus:border-[var(--color-primary)]"
          >
            {ADMIN_ACTIONS.map((a) => (
              <option key={a.id} value={a.id}>{t(`adminActions.actionLabels.${a.id}`)}</option>
            ))}
          </select>
        </div>

        <p className="text-sm text-[var(--color-on-surface-variant)]">{t(`adminActions.actionDescs.${selected.id}`)}</p>

        {selected.hasDays && (
          <div>
            <label className="block text-xs font-semibold text-[var(--color-on-surface-variant)] mb-1.5">
              {t("adminActions.days")} ({selected.daysMin}&ndash;{selected.daysMax})
            </label>
            <input
              type="number"
              min={selected.daysMin}
              max={selected.daysMax}
              value={days}
              onChange={(e) => setDays(Number(e.target.value) || selected.daysDefault)}
              className="w-32 px-3 py-2 rounded-lg bg-[var(--color-surface-container)] border border-[var(--color-outline-variant)] text-sm text-[var(--color-on-surface)] focus:outline-none focus:border-[var(--color-primary)]"
            />
          </div>
        )}

        <button
          onClick={runAction}
          disabled={loading}
          className="px-6 py-2.5 rounded-full bg-[var(--color-primary)] text-white font-semibold text-sm hover:opacity-90 transition-opacity disabled:opacity-50"
        >
          {loading ? t("adminActions.executing") : t("adminActions.execute")}
        </button>

        {feedback.message && (
          <div className={`text-sm p-3 rounded-xl ${
            feedback.kind === "success"
              ? "bg-[var(--color-success-container)] text-[var(--color-success)]"
              : "bg-[var(--color-error-container)] text-[var(--color-error)]"
          }`}>
            {feedback.message}
          </div>
        )}
      </div>

      {response && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="md3-card-elevated p-4"
        >
          <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-2">{t("adminActions.response")}</h3>
          <pre className="font-mono text-xs text-[var(--color-on-surface-variant)] whitespace-pre-wrap overflow-auto max-h-96">
            {JSON.stringify(response, null, 2)}
          </pre>
        </motion.div>
      )}
    </div>
  );
}
