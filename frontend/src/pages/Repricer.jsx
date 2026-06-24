import { useState, useEffect } from "react";
import { useI18n } from "../utils/i18n.jsx";
import { request, safeCall } from "../utils/api.js";
import { moneyFmt, numberFmt, percentFmt } from "../utils/formats.js";
import { Spinner } from "../components/StatusChip.jsx";
import DataTable from "../components/DataTable.jsx";
import { motion } from "motion/react";
import { Tag, Plus, Trash } from "@phosphor-icons/react";

export default function Repricer() {
  const { t } = useI18n();
  const [rules, setRules] = useState([]);
  const [breakeven, setBreakeven] = useState([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("rules");

  useEffect(() => {
    setLoading(true);
    Promise.all([
      safeCall(() => request("/api/v1/repricer/rules", { admin: true })),
      safeCall(() => request("/api/v1/repricer/breakeven", { admin: true })),
    ]).then(([rRes, bRes]) => {
      setRules(rRes.ok ? rRes.data : []);
      setBreakeven(bRes.ok ? bRes.data : []);
      setLoading(false);
    });
  }, []);

  const deleteRule = async (ruleId) => {
    const res = await safeCall(() =>
      request(`/api/v1/repricer/rules/${ruleId}`, { method: "DELETE", admin: true })
    );
    if (res.ok) {
      setRules((prev) => prev.filter((r) => r.rule_id !== ruleId));
    }
  };

  if (loading) return <Spinner />;

  return (
    <div className="space-y-4">
      <div className="flex gap-2 border-b border-[var(--color-outline-variant)]">
        <button
          onClick={() => setTab("rules")}
          className={`px-4 py-2 text-sm font-semibold border-b-2 transition-colors ${
            tab === "rules"
              ? "border-[var(--color-primary)] text-[var(--color-primary)]"
              : "border-transparent text-[var(--color-on-surface-variant)] hover:text-[var(--color-on-surface)]"
          }`}
        >
          Правила
        </button>
        <button
          onClick={() => setTab("breakeven")}
          className={`px-4 py-2 text-sm font-semibold border-b-2 transition-colors ${
            tab === "breakeven"
              ? "border-[var(--color-primary)] text-[var(--color-primary)]"
              : "border-transparent text-[var(--color-on-surface-variant)] hover:text-[var(--color-on-surface)]"
          }`}
        >
          Break-even анализ
        </button>
      </div>

      {tab === "rules" && (
        <div className="space-y-3">
          {rules.length === 0 && (
            <div className="text-center py-12 text-[var(--color-on-surface-variant)]">
              <Tag size={40} className="mx-auto mb-3 opacity-40" />
              <p className="font-semibold">Нет правил ценообразования</p>
              <p className="text-sm mt-1">Добавьте правило через API для управления ценами</p>
            </div>
          )}
          {rules.map((rule) => (
            <motion.div key={rule.rule_id} layout className="md3-card-elevated p-4">
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="font-semibold text-sm">
                    {rule.marketplace === "wb" ? "WB" : "Ozon"} — {rule.product_id}
                  </h3>
                  <p className="text-xs text-[var(--color-on-surface-variant)] mt-0.5">
                    {rule.account_id}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${
                    rule.is_active
                      ? "bg-green-100 text-green-700"
                      : "bg-[var(--color-surface-container)] text-[var(--color-on-surface-variant)]"
                  }`}>
                    {rule.is_active ? "Active" : "Inactive"}
                  </span>
                  <button
                    onClick={() => deleteRule(rule.rule_id)}
                    className="p-1.5 rounded-lg hover:bg-red-50 text-red-500 transition-colors"
                  >
                    <Trash size={14} />
                  </button>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-4 mt-3 text-sm">
                <div>
                  <span className="text-xs text-[var(--color-on-surface-variant)]">Min price</span>
                  <p className="font-mono font-semibold">{moneyFmt(rule.min_price)}</p>
                </div>
                <div>
                  <span className="text-xs text-[var(--color-on-surface-variant)]">Max price</span>
                  <p className="font-mono font-semibold">{moneyFmt(rule.max_price)}</p>
                </div>
                <div>
                  <span className="text-xs text-[var(--color-on-surface-variant)]">Target margin</span>
                  <p className="font-mono font-semibold">{percentFmt(rule.target_margin_percent / 100)}</p>
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      )}

      {tab === "breakeven" && (
        <section className="md3-card-elevated p-4">
          <DataTable
            rows={breakeven}
            preferredColumns={["marketplace", "account_id", "product_id", "current_price", "cost_price", "breakeven_price", "min_recommended_price", "commission_pct", "logistics_rub"]}
          />
        </section>
      )}
    </div>
  );
}
