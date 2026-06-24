import { useState, useEffect } from "react";
import { request, getAdminKey } from "../utils/api.js";
import { motion } from "motion/react";
import { Spinner } from "../components/StatusChip.jsx";

const ADMIN_ACTIONS = [
  { id: "backfill_wb_sales", label: "WB Sales Backfill", desc: "Requeue WB sales raw for a bounded window", endpoint: "/api/v1/admin/backfill", body: (d) => ({ marketplace: "wb", dataset: "sales", days: d }), hasDays: true, daysMin: 1, daysMax: 90, daysDefault: 14 },
  { id: "backfill_wb_orders", label: "WB Orders Backfill", desc: "Requeue WB orders for up to 90 days", endpoint: "/api/v1/admin/backfill", body: (d) => ({ marketplace: "wb", dataset: "orders", days: d }), hasDays: true, daysMin: 1, daysMax: 90, daysDefault: 14 },
  { id: "backfill_wb_funnel", label: "WB Funnel Backfill", desc: "Rebuild WB funnel raw data", endpoint: "/api/v1/admin/backfill", body: (d) => ({ marketplace: "wb", dataset: "funnel", days: d }), hasDays: true, daysMin: 1, daysMax: 90, daysDefault: 14 },
  { id: "backfill_ozon_postings", label: "Ozon Postings Backfill", desc: "Requeue Ozon postings ingestion", endpoint: "/api/v1/admin/backfill", body: (d) => ({ marketplace: "ozon", dataset: "postings", days: d }), hasDays: true, daysMin: 1, daysMax: 90, daysDefault: 14 },
  { id: "backfill_ozon_finance", label: "Ozon Finance Backfill", desc: "Requeue Ozon finance ingestion", endpoint: "/api/v1/admin/backfill", body: (d) => ({ marketplace: "ozon", dataset: "finance", days: d }), hasDays: true, daysMin: 1, daysMax: 365, daysDefault: 30 },
  { id: "transform_recent", label: "Transform Recent", desc: "Rebuild recent transform window", endpoint: "/api/v1/admin/transforms/recent", body: () => ({}), hasDays: false },
  { id: "transform_backfill", label: "Transform Backfill", desc: "Rebuild staging tables for a day window", endpoint: "/api/v1/admin/transforms/backfill", body: (d) => ({ days: d }), hasDays: true, daysMin: 1, daysMax: 365, daysDefault: 14 },
  { id: "marts_recent", label: "Marts Recent", desc: "Rebuild recent marts", endpoint: "/api/v1/admin/marts/recent", body: () => ({}), hasDays: false },
  { id: "marts_backfill", label: "Marts Backfill", desc: "Rebuild marts for a day window", endpoint: "/api/v1/admin/marts/backfill", body: (d) => ({ days: d }), hasDays: true, daysMin: 1, daysMax: 365, daysDefault: 14 },
  { id: "run_automation", label: "Run Automation Rules", desc: "Trigger alert automation outside schedule", endpoint: "/api/v1/admin/maintenance/run-automation", body: () => ({}), hasDays: false },
  { id: "prune_raw", label: "Prune Old Raw", desc: "Delete raw records older than retention", endpoint: "/api/v1/admin/maintenance/prune-raw", body: (d) => ({ days: d }), hasDays: true, daysMin: 30, daysMax: 3650, daysDefault: 120 },
];

export default function AdminActions() {
  const [selected, setSelected] = useState(ADMIN_ACTIONS[0]);
  const [days, setDays] = useState(ADMIN_ACTIONS[0].daysDefault || 14);
  const [response, setResponse] = useState(null);
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState({ message: "", kind: "" });

  const hasKey = !!getAdminKey();

  const runAction = async () => {
    if (!hasKey) {
      setFeedback({ message: "Admin API key required. Set it in Settings.", kind: "error" });
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
      setFeedback({ message: `${selected.label} completed successfully`, kind: "success" });
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
          <h3 className="text-sm font-bold text-[var(--color-warning)] mb-1">Admin Key Required</h3>
          <p className="text-xs text-[var(--color-on-surface-variant)]">
            Set the Admin API key in Settings (sidebar) to use these operations.
          </p>
        </div>
      )}

      <div className="md3-card-elevated p-4 space-y-4">
        <div>
          <label className="block text-xs font-semibold text-[var(--color-on-surface-variant)] mb-1.5">Action</label>
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
              <option key={a.id} value={a.id}>{a.label}</option>
            ))}
          </select>
        </div>

        <p className="text-sm text-[var(--color-on-surface-variant)]">{selected.desc}</p>

        {selected.hasDays && (
          <div>
            <label className="block text-xs font-semibold text-[var(--color-on-surface-variant)] mb-1.5">
              Days ({selected.daysMin}–{selected.daysMax})
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
          {loading ? "Executing..." : "Execute Action"}
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
          <h3 className="text-sm font-semibold text-[var(--color-on-surface)] mb-2">Response</h3>
          <pre className="font-mono text-xs text-[var(--color-on-surface-variant)] whitespace-pre-wrap overflow-auto max-h-96">
            {JSON.stringify(response, null, 2)}
          </pre>
        </motion.div>
      )}
    </div>
  );
}
